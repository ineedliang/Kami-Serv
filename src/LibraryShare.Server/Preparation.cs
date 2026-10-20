using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace LibraryShare;

public sealed record PlaybackSettings(string AudioPreference = "dolby", string SubtitlePosition = "bottom",
    int SubtitleOffset = 0, string Font = "Arial", int FontSize = 26, bool Bold = false,
    string Color = "FFFFFF", int Outline = 2)
{
    public void Validate()
    {
        if (AudioPreference is not ("default" or "dolby" or "aac") || SubtitlePosition is not ("file" or "bottom" or "top") ||
            SubtitleOffset is < -1000 or > 1000 || FontSize is < 8 or > 160 || Outline is < 0 or > 10 ||
            Font.Length is < 1 or > 100 || Font.Any(char.IsControl) || Color.Length != 6 || !Color.All(Uri.IsHexDigit))
            throw new ArgumentException("Check subtitle settings: size 8–160 pixels, offset -1000–1000, outline 0–10, color six hex digits.");
    }
}

// Completed, independently seekable files are published only after VLC finishes.
// This first UI path deliberately prepares files rather than claiming live seeks.
public sealed class Preparation(ServerOptions options, Library library, CancellationToken shutdown)
{
    private readonly object gate = new();
    private readonly string settingsFile = Path.GetFullPath(options.ConfigPath) + ".playback.json";
    public PlaybackSettings Settings { get; private set; } = Load(options.ConfigPath);
    private string status = "No preparation running.";
    private bool busy;
    private bool picking;
    private string pickerMessage = "";
    private string? pickedFolder, pickedIcon;
    public string Status { get { lock (gate) return status; } }
    public bool PickerActive { get { lock (gate) return picking; } }
    public string PickerMessage { get { lock (gate) return pickerMessage; } }
    public (string? Folder, string? Icon) TakePicked()
    {
        lock (gate) { var result = (pickedFolder, pickedIcon); pickedFolder = pickedIcon = null; return result; }
    }
    private static PlaybackSettings Load(string config)
    {
        var path = Path.GetFullPath(config) + ".playback.json";
        var result = File.Exists(path) ? JsonSerializer.Deserialize<PlaybackSettings>(File.ReadAllText(path)) ?? new() : new();
        result.Validate();
        return result;
    }
    public void Save(PlaybackSettings settings)
    {
        settings.Validate();
        lock (gate)
        {
            File.WriteAllText(settingsFile + ".tmp", JsonSerializer.Serialize(settings));
            File.Move(settingsFile + ".tmp", settingsFile, true);
            Settings = settings;
        }
    }
    private static ProcessStartInfo Command(string executable, params string[] arguments)
    {
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in arguments) start.ArgumentList.Add(arg);
        return start;
    }
    private static async Task<string> Run(ProcessStartInfo start, CancellationToken cancellation)
    {
        using var process = Process.Start(start) ?? throw new IOException("Could not launch the preparation tool.");
        using var registration = cancellation.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } });
        var output = process.StandardOutput.ReadToEndAsync(cancellation);
        var error = process.StandardError.ReadToEndAsync(cancellation);
        await process.WaitForExitAsync(cancellation);
        var result = await output;
        var diagnostic = await error;
        if (process.ExitCode != 0) throw new IOException("Preparation tool failed. " + diagnostic[^Math.Min(1200, diagnostic.Length)..]);
        return result;
    }
    public void Pick(string kind)
    {
        if (kind is not ("folder" or "icon")) throw new ArgumentException("Unknown chooser.");
        lock (gate)
        {
            if (picking) throw new ArgumentException("A chooser is already open. Finish or cancel it before browsing again.");
            picking = true; pickerMessage = "Opening " + kind + " chooser...";
            pickedFolder = pickedIcon = null;
        }
        _ = Task.Run(async () =>
        {
            try
            {
                var path = (await Run(Command("powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                    "-File", Path.Combine(options.ProjectDirectory, "scripts", "pick-path.ps1"), "-Kind", kind,
                    "-DiagnosticLog", Path.Combine(Path.GetDirectoryName(settingsFile)!, "picker.log")), shutdown)).Trim();
                lock (gate)
                {
                    if (path.Length == 0) pickerMessage = "Selection cancelled.";
                    else
                    {
                        if (kind == "folder") pickedFolder = path; else pickedIcon = path;
                        pickerMessage = kind == "folder" ? "Folder selected. Enter a label and click Add / update folder." : "Icon selected. Click Save server identity.";
                    }
                }
            }
            catch (Exception e) when (e is IOException or System.ComponentModel.Win32Exception or OperationCanceledException)
            { lock (gate) pickerMessage = "Chooser failed: " + e.Message; }
            finally { lock (gate) picking = false; }
        }, CancellationToken.None);
    }
    public async Task<ServerIcon> ImportIcon(string source, CancellationToken cancellation)
    {
        if (!File.Exists(source)) throw new ArgumentException("Choose an existing PNG, JPEG, BMP, GIF, or ICO image.");
        var destination = Path.Combine(Path.GetDirectoryName(settingsFile)!, "server-icon-" + Guid.NewGuid().ToString("N") + ".png");
        await Run(Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            Path.Combine(options.ProjectDirectory, "scripts", "import-icon.ps1"), "-Source", Path.GetFullPath(source), "-Destination", destination), cancellation);
        return new(destination, "image/png", 256, 256, 32);
    }
    public void Start(string id, bool burn, int subtitle, bool full, string sidecarId = "")
    {
        if (!library.Snapshot.Entries.TryGetValue(id, out var source) || source.IsFolder || source.Mime?.StartsWith("video/", StringComparison.Ordinal) != true ||
            Library.HasReparsePoint(source.Path!, source.Root!)) throw new ArgumentException("Select a shared video file.");
        if (subtitle is < 0 or > 99) throw new ArgumentException("Subtitle index must be 0–99.");
        var sidecar = sidecarId.Length == 0 ? null : source.Subtitles.FirstOrDefault(s => s.Id == sidecarId)
            ?? throw new ArgumentException("That SRT is not associated with the selected video. Reload its subtitle choices.");
        if (sidecar is not null && (Library.HasReparsePoint(sidecar.Path, sidecar.Root) || !File.Exists(sidecar.Path)))
            throw new ArgumentException("The selected SRT is unavailable. Rescan the library.");
        PlaybackSettings settings;
        lock (gate)
        {
            if (busy) throw new ArgumentException("A file is already being prepared. Refresh for its status.");
            busy = true; settings = Settings; status = "Preparing " + source.Title + " — Refresh for completion.";
        }
        _ = Task.Run(async () =>
        {
            try
            {
                var work = Path.Combine(Path.GetDirectoryName(settingsFile)!, "preparation", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(work);
                var config = Path.Combine(work, "settings.json");
                File.WriteAllText(config, JsonSerializer.Serialize(settings));
                var output = Path.Combine(work, "output.mkv");
                var jobFile = Path.Combine(work, "job.json");
                string? copiedSubtitle = null;
                if (sidecar is not null)
                {
                    if (Library.HasReparsePoint(sidecar.Path, sidecar.Root)) throw new IOException("The selected SRT is no longer a regular shared file.");
                    copiedSubtitle = Path.Combine(work, "selected.srt");
                    await using var input = new FileStream(sidecar.Path, FileMode.Open, FileAccess.Read, FileShare.Read);
                    if (input.Length is <= 0 or > 16 * 1024 * 1024) throw new IOException("SRT files must be nonempty and at most 16 MiB.");
                    await using var destination = new FileStream(copiedSubtitle, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                    await input.CopyToAsync(destination, shutdown);
                }
                var job = new PreparationJob(source.Path!, output, Environment.GetEnvironmentVariable("VLC_DIR") ?? @"C:\Program Files\VideoLAN\VLC",
                    settings, burn, subtitle, full ? null : 120, ExternalSubtitle: burn ? copiedSubtitle : null);
                await File.WriteAllTextAsync(jobFile, JsonSerializer.Serialize(job), shutdown);
                var start = Command(Environment.ProcessPath!, "--prepare-worker", jobFile);
                if (string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath), "dotnet", StringComparison.OrdinalIgnoreCase))
                    start.ArgumentList.Insert(0, typeof(Preparation).Assembly.Location);
                await Run(start, shutdown);
                shutdown.ThrowIfCancellationRequested();
                if (!library.Snapshot.Entries.ContainsKey(id)) throw new IOException("Source was removed from sharing; output was not published.");
                if (sidecar is not null && !library.Snapshot.Entries[id].Subtitles.Any(s => s.Id == sidecar.Id))
                    throw new IOException("Selected SRT was removed from sharing; output was not published.");
                var folder = Path.Combine(Path.GetDirectoryName(settingsFile)!, "Prepared Media");
                Directory.CreateDirectory(folder);
                var title = Path.GetFileNameWithoutExtension(source.Title);
                if (title.Length > 90) title = title[..90];
                var suffix = burn ? $"Captions {settings.SubtitlePosition}" : $"Audio {settings.AudioPreference}";
                var target = Path.Combine(folder, $"{title} - {suffix} - {(full ? "Full" : "2 min")} - {DateTime.Now:HHmmss}-{Guid.NewGuid().ToString("N")[..4]}.mkv");
                var targetSubtitle = copiedSubtitle is not null && !burn ? Path.ChangeExtension(target, ".srt") : null;
                try
                {
                    // Publish captions first: a simultaneous rescan can never list
                    // this completed video before its selected sidecar is ready.
                    if (targetSubtitle is not null) File.Move(copiedSubtitle!, targetSubtitle);
                    File.Move(output, target);
                }
                catch
                {
                    if (targetSubtitle is not null && File.Exists(targetSubtitle)) File.Delete(targetSubtitle);
                    throw;
                }
                await library.Change("add", folder, shutdown, "Prepared for TV", "video");
                lock (gate) status = "Ready in Prepared for TV: " + Path.GetFileName(target);
            }
            catch (Exception e) when (e is IOException or ArgumentException or UnauthorizedAccessException or System.ComponentModel.Win32Exception or OperationCanceledException)
            { lock (gate) status = "Preparation failed: " + e.Message; }
            finally { lock (gate) busy = false; }
        }, CancellationToken.None);
    }

    public static string StartCommand(ServerOptions options)
    {
        var encodedPath = Convert.ToBase64String(Encoding.UTF8.GetBytes(options.ProjectDirectory));
        var code = "$root=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encodedPath + "')); & (Join-Path $root 'scripts\\launch-helper.ps1') -Port " + options.Port +
            (System.Net.IPAddress.IsLoopback(options.Listen) ? " -LocalOnly" : "");
        return "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand " + Convert.ToBase64String(Encoding.Unicode.GetBytes(code));
    }
}
