using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using LibraryShare;

if (args.Length == 2 && args[0] == "--prepare-worker")
{
    Environment.ExitCode = await NativePreparation.Run(args[1]);
    return;
}

var options = ServerOptions.Parse(args);
var library = new Library(options.ConfigPath);
// Keep the local pairing stable across helper restarts; never log this credential.
var tokenPath = Path.GetFullPath(options.ConfigPath) + ".control-token";
var token = File.Exists(tokenPath) ? File.ReadAllText(tokenPath).Trim() : Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
if (token.Length != 64 || !token.All(Uri.IsHexDigit)) throw new InvalidDataException("Invalid local control credential.");
if (!File.Exists(tokenPath)) File.WriteAllText(tokenPath, token, new UTF8Encoding(false));
var builder = WebApplication.CreateSlimBuilder();
builder.Logging.SetMinimumLevel(LogLevel.Warning);
builder.WebHost.ConfigureKestrel(k =>
{
    k.AddServerHeader = false;
    k.Limits.MaxRequestBodySize = 65536;
    k.Listen(options.Listen, options.Port);
});
builder.Services.AddSingleton(options);
builder.Services.AddSingleton(library);
builder.Services.AddSingleton<Events>();
builder.Services.AddHostedService<Ssdp>();
builder.Services.AddSingleton<VlcLifetime>();
builder.Services.AddHostedService(services => services.GetRequiredService<VlcLifetime>());
builder.Services.Configure<HostOptions>(host => host.ShutdownTimeout = TimeSpan.FromSeconds(5));
var app = builder.Build();
var events = app.Services.GetRequiredService<Events>();
var vlcLifetime = app.Services.GetRequiredService<VlcLifetime>();
var preparation = new Preparation(options, library, app.Lifetime.ApplicationStopping);
var firewall = new FirewallSetup(options, app.Lifetime.ApplicationStopping);
events.Start();

// Local control is authenticated and never accessible to a TV or other LAN client.
app.Use(async (context, next) =>
{
    var remote = context.Connection.RemoteIpAddress;
    if (remote is null || !ServerOptions.IsLocalNetwork(remote)) { context.Response.StatusCode = 403; return; }
    if (context.Request.Path.StartsWithSegments("/local"))
    {
        var supplied = context.Request.Query["token"].ToString();
        if (!IPAddress.IsLoopback(remote) || context.Request.Host.Host != "127.0.0.1" ||
            supplied.Length != token.Length || !CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(supplied), Encoding.ASCII.GetBytes(token)))
        { context.Response.StatusCode = 403; return; }
        context.Response.Headers.CacheControl = "no-store";
    }
    await next(context);
});

app.MapGet("/local", async (HttpContext context) =>
{
    var action = context.Request.Query["action"].ToString();
    try
    {
        var query = context.Request.Query;
        MediaEntry? subtitleVideo = null;
        if (action == "settings")
            preparation.Save(new(query["audio"].ToString(), query["position"].ToString(), int.Parse(query["offset"].ToString()),
                query["font"].ToString().Trim(), int.Parse(query["size"].ToString()), query["bold"] == "true",
                query["color"].ToString().Trim().TrimStart('#').ToUpperInvariant(), int.Parse(query["outline"].ToString())));
        else if (action == "prepare") preparation.Start(query["id"].ToString(), query["burn"] == "true", int.Parse(query["subtitle"].ToString()), query["full"] == "true", query["sidecar"].ToString());
        else if (action == "subtitles")
        {
            if (!library.Snapshot.Entries.TryGetValue(query["id"].ToString(), out subtitleVideo) || subtitleVideo.Mime?.StartsWith("video/", StringComparison.Ordinal) != true)
                throw new ArgumentException("Select a shared video first.");
        }
        else if (action is "pick-folder" or "pick-icon") preparation.Pick(action[5..]);
        else if (action == "picker-wait")
        {
            // Short waits keep the extension watchdog alive while the separate
            // native chooser runs, without a busy loop or blocking other clients.
            for (var attempt = 0; attempt < 15 && preparation.PickerActive; attempt++)
                await Task.Delay(50, context.RequestAborted);
        }
        else if (action is "firewall-allow" or "firewall-check") firewall.Start(action == "firewall-allow");
        else if (action == "firewall-wait")
        {
            for (var attempt = 0; attempt < 15 && firewall.Active; attempt++)
                await Task.Delay(50, context.RequestAborted);
        }
        else if (action == "shutdown") app.Lifetime.StopApplication();
        else if (action == "attach-owner") vlcLifetime.Attach(int.Parse(query["pid"].ToString()), long.Parse(query["created"].ToString()));
        else if (action == "identity")
        {
            var icon = query["icon"].ToString() is { Length: > 0 } path ? await preparation.ImportIcon(path, context.RequestAborted) : null;
            await library.Change(action, null, context.RequestAborted, name: query["name"], icon: icon, clearIcon: query["clearIcon"] == "true");
        }
        else if (action is not ("" or "status"))
            await library.Change(action, query["folder"], context.RequestAborted,
                query.ContainsKey("label") ? query["label"].ToString() : null, query.ContainsKey("mediaType") ? query["mediaType"].ToString() : null);
        var snapshot = library.Snapshot;
        var summary = $"Sharing: {(library.Config.Enabled ? "ON" : "OFF")}\n" +
            $"Library: {snapshot.Entries.Values.Count(e => !e.IsFolder)} files in {library.Config.Folders.Count} shared folders\n" +
            $"Active HTTP transfers: {library.Transfers.Count}\n" +
            $"Network address: {options.BaseUrl}\n" +
            $"Discovery: {(options.NoSsdp ? "off (local test mode)" : "SSDP requested; see server log for errors")}\n" +
            "Playback: original files + explicitly prepared TV versions\n" + preparation.Status +
            (preparation.PickerMessage.Length == 0 ? "" : "\n" + preparation.PickerMessage);
        var settings = preparation.Settings;
        var picked = preparation.TakePicked();
        return Results.Text(Upnp.Xml(new XElement("library", new XElement("summary", summary),
            new XElement("pickerActive", preparation.PickerActive), new XElement("pickerMessage", preparation.PickerMessage),
            new XElement("vlcOwners", vlcLifetime.OwnerCount),
            new XElement("firewallActive", firewall.Active), new XElement("firewallMessage", firewall.Message), new XElement("firewallState", firewall.State),
            new XElement("serverName", library.Config.Name),
            new XElement("audioPreference", settings.AudioPreference), new XElement("subtitlePosition", settings.SubtitlePosition),
            new XElement("subtitleOffset", settings.SubtitleOffset), new XElement("font", settings.Font),
            new XElement("fontSize", settings.FontSize), new XElement("bold", settings.Bold), new XElement("color", settings.Color), new XElement("outline", settings.Outline),
            picked.Folder is null ? null : new XElement("pickedFolder", picked.Folder),
            picked.Icon is null ? null : new XElement("pickedIcon", picked.Icon),
            new XElement("folders", library.Config.Folders.ToArray().SelectMany(f => {
                var folder = library.Config.FolderSettings.GetValueOrDefault(f) ?? new("", "all");
                return new[] { new XElement("folder", f), new XElement("folderLabel", folder.Label), new XElement("folderType", folder.MediaType),
                    new XElement("folderDisplay", $"{(folder.Label.Length == 0 ? new DirectoryInfo(f).Name : folder.Label)} [{folder.MediaType}] — {f}") }; })),
            new XElement("videos", snapshot.Entries.Values.Where(e => !e.IsFolder && e.Mime!.StartsWith("video/", StringComparison.Ordinal)).Take(500)
                .SelectMany(e => new[] { new XElement("videoId", e.Id), new XElement("videoTitle", e.Title) })),
            subtitleVideo is null ? null : new XElement("sidecars", subtitleVideo.Subtitles.SelectMany(s => new[] {
                new XElement("sidecarId", s.Id), new XElement("sidecarName", s.Name), new XElement("sidecarLanguage", s.Language) })),
            subtitleVideo is null ? null : new XElement("subtitleMessage", $"{subtitleVideo.Subtitles.Length} matching SRT file(s). Choose a subtitle source below."),
            new XElement("warnings", library.ScanWarnings.Select(w => new XElement("warning", w))),
            new XElement("transfers", library.Transfers.Values.Select(t => new XElement("transfer",
                $"ACTIVE | {t.Client}: {t.Title} [{t.Method} {t.Range}]"))),
            new XElement("recentTransfers", library.RecentTransfers.Snapshot().Select(t => new XElement("recentTransfer",
                $"RECENT {t.Finished.ToLocalTime():HH:mm:ss} | {t.Request.Client}: {t.Request.Title} " +
                $"[{t.Request.Method} HTTP {t.Status}; {t.Outcome}; {t.Request.Range}]"))))), "text/xml; charset=utf-8");
    }
    catch (Exception e) when (e is ArgumentException or IOException or UnauthorizedAccessException or FormatException or OverflowException)
    { return Results.Text(Upnp.Xml(new XElement("error", e.Message)), "text/xml; charset=utf-8"); }
});

app.MapGet("/device.xml", () => Results.Text(Upnp.Description(library.Config), "text/xml; charset=utf-8"));
app.MapGet("/server-icon.png", () => library.Config.Icon is { } icon && File.Exists(icon.File)
    ? Results.File(icon.File, icon.Mime) : Results.NotFound());
app.MapGet("/upnp/{service}.xml", (string service) => service is "content" or "connection"
    ? Results.Text(Upnp.Scpd(service), "text/xml; charset=utf-8") : Results.NotFound());

app.MapPost("/upnp/{service}/control", async (HttpContext context, string service) =>
{
    if (service is not ("content" or "connection")) return Results.NotFound();
    if (!library.Config.Enabled) return Results.StatusCode(503);
    try
    {
        var action = await Upnp.ReadAction(context.Request, context.RequestAborted);
        return Results.Text(Upnp.Respond(service, action, library, options.BaseUrl), "text/xml; charset=utf-8");
    }
    catch (UpnpFault fault) { return Results.Text(Upnp.Fault(fault.Code, fault.Message), "text/xml; charset=utf-8", statusCode: 500); }
    catch (Exception e) when (e is XmlException or InvalidOperationException)
    { return Results.Text(Upnp.Fault(402, "Invalid Args"), "text/xml; charset=utf-8", statusCode: 500); }
});

app.MapMethods("/upnp/{service}/event", ["SUBSCRIBE", "UNSUBSCRIBE"], (HttpContext context, string service) =>
    service is "content" or "connection" ? events.Handle(context, service) : Results.NotFound());

app.MapMethods("/media/{id}/{name}", ["GET", "HEAD"], async (HttpContext context, string id, string name) =>
{
    if (!library.Config.Enabled) { context.Response.StatusCode = 503; return; }
    if (!library.Snapshot.Entries.TryGetValue(id, out var entry) || entry.IsFolder)
    { context.Response.StatusCode = 404; return; }
    SubtitleFile? subtitle = null;
    if (Path.GetExtension(name).Equals(".srt", StringComparison.OrdinalIgnoreCase))
    {
        subtitle = entry.Subtitles.FirstOrDefault(s => s.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
        if (subtitle is null) { context.Response.StatusCode = 404; return; }
    }
    var path = subtitle?.Path ?? entry.Path!;
    var root = subtitle?.Root ?? entry.Root!;
    try
    {
        if (Library.HasReparsePoint(entry.Path!, entry.Root!) || Library.HasReparsePoint(path, root) || !File.Exists(entry.Path) || !File.Exists(path))
        { context.Response.StatusCode = 404; return; }
        if (subtitle is not null && new FileInfo(path).Length is <= 0 or > 16 * 1024 * 1024)
        { context.Response.StatusCode = 404; return; }
    }
    catch (Exception e) when (e is IOException or UnauthorizedAccessException)
    { context.Response.StatusCode = 404; return; }
    if (!await library.TransferSlots.WaitAsync(0, context.RequestAborted))
    { context.Response.StatusCode = 503; context.Response.Headers.RetryAfter = "2"; return; }
    var transferId = Guid.NewGuid().ToString("N");
    using var stopTransfer = CancellationTokenSource.CreateLinkedTokenSource(context.RequestAborted, app.Lifetime.ApplicationStopping);
    void StopIfDisabled() { if (!library.Config.Enabled || !library.Snapshot.Entries.TryGetValue(id, out var current) ||
        subtitle is not null && !current.Subtitles.Any(s => s.Id == subtitle.Id)) stopTransfer.Cancel(); }
    library.Changed += StopIfDisabled;
    var transfer = new Transfer(transferId, context.Connection.RemoteIpAddress!.ToString(), subtitle?.Name ?? entry.Title,
        context.Request.Headers.Range.ToString() is { Length: > 0 } range ? range : "whole file", DateTime.UtcNow,
        context.Request.Method, subtitle is null ? id : id + ":" + subtitle.Id);
    library.Transfers[transferId] = transfer;
    var outcome = "response finished";
    var previousAbort = context.RequestAborted;
    context.RequestAborted = stopTransfer.Token;
    try
    {
        StopIfDisabled();
        if (stopTransfer.IsCancellationRequested) { context.Response.StatusCode = 503; return; }
        if (subtitle is null)
        {
            context.Response.Headers["contentFeatures.dlna.org"] = Upnp.Features;
            context.Response.Headers["transferMode.dlna.org"] = "Streaming";
            if (entry.Subtitles.FirstOrDefault() is { } primary)
                context.Response.Headers["CaptionInfo.sec"] = Upnp.SubtitleUrl(options.BaseUrl, entry, primary);
        }
        // Kestrel's file result implements independent byte ranges, HEAD, 206/416,
        // Last-Modified, and cancellation; playback positions never live in global state.
        await Results.File(path, subtitle is null ? entry.Mime : "text/srt", enableRangeProcessing: true,
            lastModified: File.GetLastWriteTimeUtc(path)).ExecuteAsync(context);
    }
    catch (OperationCanceledException) when (stopTransfer.IsCancellationRequested) { outcome = "interrupted"; context.Abort(); }
    catch (IOException) { outcome = "interrupted"; context.Abort(); }
    catch { outcome = "failed"; throw; }
    finally
    {
        context.RequestAborted = previousAbort;
        library.Changed -= StopIfDisabled;
        library.RecentTransfers.Record(transfer, context.Response.StatusCode, outcome);
        library.Transfers.TryRemove(transferId, out _);
        library.TransferSlots.Release();
    }
});

await app.StartAsync();
Directory.CreateDirectory(options.ExtensionDirectory);
Directory.CreateDirectory(Path.Combine(options.ExtensionDirectory, "modules"));
var extensionSource = Path.Combine(options.ProjectDirectory, "vlc", "library_share.lua");
File.Copy(extensionSource, Path.Combine(options.ExtensionDirectory, "library_share.lua"), true);
File.WriteAllText(Path.Combine(options.ExtensionDirectory, "modules", "library_share_config.lua"),
    $"return {{ port = {options.Port}, token = \"{token}\", start_command = \"{Preparation.StartCommand(options)}\", manage_lifetime = {(File.Exists(Path.Combine(options.ProjectDirectory, "runtime.json")) ? "true" : "false")} }}\n", new UTF8Encoding(false));
Console.WriteLine($"Library Share prototype: {options.BaseUrl}");
Console.WriteLine($"Sharing {(library.Config.Enabled ? "ON" : "OFF")}. Config: {Path.GetFullPath(options.ConfigPath)}");
Console.WriteLine($"Staged VLC extension: {Path.GetFullPath(options.ExtensionDirectory)}");
Console.WriteLine("Use the extension to add folders and enable sharing. Ctrl+C stops the helper.");
await app.WaitForShutdownAsync();

namespace LibraryShare
{
    public sealed record ServerOptions(string ProjectDirectory, string ConfigPath, string ExtensionDirectory,
        IPAddress Listen, IPAddress Advertise, int Port, bool NoSsdp, int OwnerPid, long OwnerStarted)
    {
        public string BaseUrl => $"http://{Advertise}:{Port}";
        public static ServerOptions Parse(string[] args)
        {
            var values = new Dictionary<string, string>();
            foreach (var pair in args.Chunk(2))
            {
                if (pair.Length != 2 || pair[0] is not ("--project" or "--config" or "--extension-dir" or "--listen" or "--advertise" or "--port" or "--no-ssdp" or "--owner-pid" or "--owner-started"))
                    throw new ArgumentException("Options take values: --project --config --extension-dir --listen --advertise --port --no-ssdp true|false --owner-pid --owner-started");
                values.Add(pair[0], pair[1]);
            }
            var project = Path.GetFullPath(values.GetValueOrDefault("--project", Directory.GetCurrentDirectory()));
            var listen = IPAddress.Parse(values.GetValueOrDefault("--listen", "127.0.0.1"));
            var advertise = IPAddress.Parse(values.GetValueOrDefault("--advertise", listen.Equals(IPAddress.Any) ? DetectAddress() : listen.ToString()));
            var port = int.Parse(values.GetValueOrDefault("--port", "57642"));
            if (listen.AddressFamily != AddressFamily.InterNetwork || advertise.AddressFamily != AddressFamily.InterNetwork || port is < 1 or > 65535 || advertise.Equals(IPAddress.Any))
                throw new ArgumentException("Choose an IPv4 listening/advertised address and a valid port.");
            return new(project, values.GetValueOrDefault("--config", Path.Combine(project, "build", "library.json")),
                values.GetValueOrDefault("--extension-dir", Path.Combine(project, "build", "vlc-extension")),
                listen, advertise, port, bool.Parse(values.GetValueOrDefault("--no-ssdp", IPAddress.IsLoopback(advertise) ? "true" : "false")),
                int.Parse(values.GetValueOrDefault("--owner-pid", "0")), long.Parse(values.GetValueOrDefault("--owner-started", "0")));
        }
        private static string DetectAddress()
        {
            using var route = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            try
            {
                // UDP Connect chooses a route; no datagram is sent.
                route.Connect("192.0.2.1", 9);
                return ((IPEndPoint)route.LocalEndPoint!).Address.ToString();
            }
            catch (SocketException)
            {
                return NetworkInterface.GetAllNetworkInterfaces().Where(n => n.OperationalStatus == OperationalStatus.Up)
                    .SelectMany(n => n.GetIPProperties().UnicastAddresses).Select(a => a.Address)
                    .First(a => a.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(a)).ToString();
            }
        }
        public static bool IsLocalNetwork(IPAddress ip)
        {
            if (IPAddress.IsLoopback(ip)) return true;
            var b = ip.MapToIPv4().GetAddressBytes();
            return b[0] == 10 || (b[0] == 172 && b[1] is >= 16 and <= 31) ||
                (b[0] == 192 && b[1] == 168) || (b[0] == 169 && b[1] == 254);
        }
    }
}
