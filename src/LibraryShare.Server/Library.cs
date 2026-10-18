using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace LibraryShare;

public sealed class ShareConfig
{
    public string Name { get; set; } = "VLC Shared Library";
    public Guid Id { get; set; } = Guid.NewGuid();
    public bool Enabled { get; set; }
    public List<string> Folders { get; set; } = [];
    public int MaxConcurrentTransfers { get; set; } = 16;
    public Dictionary<string, FolderSettings> FolderSettings { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public ServerIcon? Icon { get; set; }
}

public sealed record FolderSettings(string Label, string MediaType);
public sealed record ServerIcon(string File, string Mime, int Width, int Height, int Depth);

public sealed record MediaEntry(string Id, string Parent, string Title, string? Path,
    string? Root, string? Mime, string MediaClass, long Size = 0)
{
    public bool IsFolder => Mime is null;
}

public sealed record LibrarySnapshot(IReadOnlyDictionary<string, MediaEntry> Entries, uint UpdateId);
public sealed record Transfer(string Id, string Client, string Title, string Range, DateTime Started,
    string Method = "GET", string MediaId = "");
public sealed record RecentTransfer(Transfer Request, DateTime Finished, int Status, string Outcome);

// Keep short requests visible between manual refreshes. These are network
// observations, never inferred play/pause sessions. Nothing is saved to disk.
public sealed class TransferHistory
{
    private readonly object gate = new();
    private readonly Dictionary<(string Client, string Media), RecentTransfer> recent = new();
    private void Prune(DateTime now)
    {
        foreach (var key in recent.Where(p => now - p.Value.Finished > TimeSpan.FromMinutes(10)).Select(p => p.Key).ToArray()) recent.Remove(key);
        foreach (var key in recent.OrderByDescending(p => p.Value.Finished).Skip(50).Select(p => p.Key).ToArray()) recent.Remove(key);
    }
    public void Record(Transfer request, int status, string outcome)
    {
        lock (gate)
        {
            var now = DateTime.UtcNow;
            recent[(request.Client, request.MediaId)] = new(request, now, status, outcome);
            Prune(now);
        }
    }
    public RecentTransfer[] Snapshot()
    {
        lock (gate)
        {
            Prune(DateTime.UtcNow);
            return recent.Values.OrderByDescending(t => t.Finished).ToArray();
        }
    }
}

public sealed class Library
{
    public static readonly IReadOnlyDictionary<string, (string Mime, string Class)> Formats =
        new Dictionary<string, (string, string)>(StringComparer.OrdinalIgnoreCase)
        {
            [".mp4"] = ("video/mp4", "object.item.videoItem"),
            [".m4v"] = ("video/mp4", "object.item.videoItem"),
            [".mkv"] = ("video/x-matroska", "object.item.videoItem"),
            [".mov"] = ("video/quicktime", "object.item.videoItem"),
            [".avi"] = ("video/avi", "object.item.videoItem"),
            [".ts"] = ("video/mp2t", "object.item.videoItem"),
            [".m2ts"] = ("video/mp2t", "object.item.videoItem"),
            [".mpg"] = ("video/mpeg", "object.item.videoItem"),
            [".mpeg"] = ("video/mpeg", "object.item.videoItem"),
            [".webm"] = ("video/webm", "object.item.videoItem"),
            [".wmv"] = ("video/x-ms-wmv", "object.item.videoItem"),
            [".mp3"] = ("audio/mpeg", "object.item.audioItem.musicTrack"),
            [".flac"] = ("audio/flac", "object.item.audioItem.musicTrack"),
            [".m4a"] = ("audio/mp4", "object.item.audioItem.musicTrack"),
            [".wav"] = ("audio/wav", "object.item.audioItem.musicTrack"),
            [".ogg"] = ("audio/ogg", "object.item.audioItem.musicTrack"),
            [".jpg"] = ("image/jpeg", "object.item.imageItem.photo"),
            [".jpeg"] = ("image/jpeg", "object.item.imageItem.photo"),
            [".png"] = ("image/png", "object.item.imageItem.photo")
        };

    private readonly string configPath;
    private readonly SemaphoreSlim changes = new(1, 1);
    private LibrarySnapshot snapshot = new(new Dictionary<string, MediaEntry>(), 0);
    public ShareConfig Config { get; private set; }
    public LibrarySnapshot Snapshot => Volatile.Read(ref snapshot);
    public ConcurrentDictionary<string, Transfer> Transfers { get; } = new();
    public TransferHistory RecentTransfers { get; } = new();
    public SemaphoreSlim TransferSlots { get; }
    public event Action? Changed;
    public string[] ScanWarnings { get; private set; } = [];

    public Library(string path)
    {
        configPath = System.IO.Path.GetFullPath(path);
        Config = File.Exists(path)
            ? JsonSerializer.Deserialize<ShareConfig>(File.ReadAllText(path)) ?? throw new InvalidDataException("Invalid config")
            : new();
        Config.FolderSettings = new(Config.FolderSettings, StringComparer.OrdinalIgnoreCase);
        if (Config.MaxConcurrentTransfers is < 4 or > 128)
            throw new InvalidDataException("MaxConcurrentTransfers must be between 4 and 128.");
        TransferSlots = new(Config.MaxConcurrentTransfers);
        Save();
        Scan();
    }

    private void Save()
    {
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(configPath)!);
        File.WriteAllText(configPath + ".tmp", JsonSerializer.Serialize(Config, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(configPath + ".tmp", configPath, true);
    }

    public async Task Change(string action, string? folder, CancellationToken cancellation,
        string? label = null, string? mediaType = null, string? name = null, ServerIcon? icon = null, bool clearIcon = false)
    {
        await changes.WaitAsync(cancellation);
        try
        {
            switch (action)
            {
                case "add":
                    if (string.IsNullOrWhiteSpace(folder)) throw new ArgumentException("Enter a folder path.");
                    var full = System.IO.Path.TrimEndingDirectorySeparator(System.IO.Path.GetFullPath(folder));
                    if (!Directory.Exists(full)) throw new ArgumentException("That folder does not exist.");
                    if (HasReparsePoint(full, full)) throw new ArgumentException("Use a real folder, not a junction or symbolic link.");
                    if (label is not null || mediaType is not null)
                    {
                        var kind = mediaType ?? "all";
                        if (kind is not ("all" or "video" or "audio" or "image")) throw new ArgumentException("Choose All, Video, Music, or Photos.");
                        var title = label?.Trim() ?? "";
                        if (title.Length > 100 || title.Any(char.IsControl)) throw new ArgumentException("Folder labels must be at most 100 characters.");
                        Config.FolderSettings[full] = new(title, kind);
                    }
                    if (!Config.Folders.Contains(full, StringComparer.OrdinalIgnoreCase)) Config.Folders.Add(full);
                    break;
                case "remove":
                    Config.Folders.RemoveAll(p => string.Equals(p, folder, StringComparison.OrdinalIgnoreCase));
                    if (folder is not null) Config.FolderSettings.Remove(folder);
                    break;
                case "identity":
                    var serverName = name?.Trim() ?? "";
                    if (serverName.Length is < 1 or > 100 || serverName.Any(char.IsControl)) throw new ArgumentException("Enter a server name (1–100 characters).");
                    Config.Name = serverName;
                    if (clearIcon || icon is not null) Config.Icon = icon;
                    break;
                case "enable": Config.Enabled = true; break;
                case "disable": Config.Enabled = false; break;
                case "rescan": break;
                default: throw new ArgumentException("Unknown control action.");
            }
            // Scanning happens off the HTTP thread and readers retain the previous complete snapshot.
            if (action is "add" or "remove" or "rescan" or "identity") await Task.Run(Scan, cancellation);
            Save();
        }
        finally { changes.Release(); }
        Changed?.Invoke();
    }

    private void Scan()
    {
        var entries = new Dictionary<string, MediaEntry>
        {
            ["0"] = new("0", "-1", Config.Name, null, null, null, "object.container")
        };
        var warnings = new List<string>();
        foreach (var configured in Config.Folders.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var root = System.IO.Path.GetFullPath(configured);
            var settings = Config.FolderSettings.GetValueOrDefault(root) ?? new("", "all");
            if (!Directory.Exists(root) || HasReparsePoint(root, root))
            {
                warnings.Add($"Unavailable folder: {root}");
                continue;
            }
            var stack = new Stack<(string Path, string Parent)>();
            stack.Push((root, "0"));
            while (stack.TryPop(out var directory))
            {
                var id = EntryId(directory.Path);
                var title = new DirectoryInfo(directory.Path).Name;
                if (directory.Parent == "0" && settings.Label.Length > 0) title = settings.Label;
                entries[id] = new(id, directory.Parent, title.Length == 0 ? directory.Path : title,
                    directory.Path, root, null, "object.container.storageFolder");
                try
                {
                    var options = new EnumerationOptions { IgnoreInaccessible = true,
                        AttributesToSkip = FileAttributes.ReparsePoint | FileAttributes.System | FileAttributes.Hidden };
                    foreach (var child in new DirectoryInfo(directory.Path).EnumerateFileSystemInfos("*", options))
                    {
                        if ((child.Attributes & FileAttributes.Directory) != 0) stack.Push((child.FullName, id));
                        else if (child is FileInfo file && Formats.TryGetValue(file.Extension, out var format))
                        {
                            if (settings.MediaType != "all" && !format.Mime.StartsWith(settings.MediaType + "/", StringComparison.Ordinal)) continue;
                            var childId = EntryId(file.FullName);
                            entries[childId] = new(childId, id, file.Name, file.FullName, root,
                                format.Mime, format.Class, file.Length);
                        }
                    }
                }
                catch (Exception e) when (e is IOException or UnauthorizedAccessException)
                { warnings.Add($"Could not read folder: {directory.Path}"); }
            }
        }
        ScanWarnings = warnings.ToArray();
        Volatile.Write(ref snapshot, new(entries, unchecked(Snapshot.UpdateId + 1)));
    }

    public static string EntryId(string path) => Convert.ToHexString(
        SHA256.HashData(Encoding.UTF8.GetBytes(System.IO.Path.GetFullPath(path).ToUpperInvariant())))[..32];

    public static bool HasReparsePoint(string path, string root)
    {
        var fullRoot = System.IO.Path.TrimEndingDirectorySeparator(System.IO.Path.GetFullPath(root));
        var relative = System.IO.Path.GetRelativePath(fullRoot, path);
        if (System.IO.Path.IsPathRooted(relative) || relative == ".." || relative.StartsWith(".." + System.IO.Path.DirectorySeparatorChar)) return true;
        // Recheck ancestors on every request so replacing a scanned directory with a junction
        // cannot make an indexed URL expose a file outside the chosen share.
        for (var current = new FileInfo(System.IO.Path.GetFullPath(path)) as FileSystemInfo;
             current is not null; current = Directory.GetParent(current.FullName))
        {
            if ((current.Attributes & FileAttributes.ReparsePoint) != 0) return true;
        }
        return false;
    }
}
