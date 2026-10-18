using System.Net;
using System.Net.Sockets;
using System.Text;

namespace LibraryShare;

public sealed class Ssdp(Library library, ServerOptions options, ILogger<Ssdp> logger) : BackgroundService
{
    private static readonly IPEndPoint Multicast = new(IPAddress.Parse("239.255.255.250"), 1900);
    private UdpClient? socket;
    private readonly SemaphoreSlim sending = new(1, 1);
    private string Udn => $"uuid:{library.Config.Id}";
    private string[] Targets => ["upnp:rootdevice", Udn, Upnp.MediaServer, Upnp.ContentDirectory, Upnp.ConnectionManager];
    private string Usn(string target) => target == Udn ? Udn : $"{Udn}::{target}";

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (options.NoSsdp) return;
        using var workerLifetime = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
        stoppingToken = workerLifetime.Token;
        try
        {
            socket = new UdpClient(AddressFamily.InterNetwork);
            socket.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
            socket.Client.Bind(new IPEndPoint(IPAddress.Any, 1900));
            socket.JoinMulticastGroup(Multicast.Address, options.Advertise);
            socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastInterface, options.Advertise.GetAddressBytes());
            socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastTimeToLive, 2);
        }
        catch (SocketException e)
        {
            logger.LogWarning("SSDP could not start: {Message}. HTTP remains available; check UDP port 1900 and the selected LAN address.", e.Message);
            socket?.Dispose(); socket = null;
            return;
        }
        library.Changed += OnChanged;
        var announcements = AnnounceLoop(stoppingToken);
        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                var received = await socket.ReceiveAsync(stoppingToken);
                if (!library.Config.Enabled || received.Buffer.Length > 8192) continue;
                var lines = Encoding.ASCII.GetString(received.Buffer).Split("\r\n");
                if (!string.Equals(lines[0], "M-SEARCH * HTTP/1.1", StringComparison.OrdinalIgnoreCase)) continue;
                var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (var line in lines.Skip(1))
                {
                    var colon = line.IndexOf(':');
                    if (colon > 0) headers[line[..colon].Trim()] = line[(colon + 1)..].Trim();
                }
                if (!headers.TryGetValue("MAN", out var man) || !man.Equals("\"ssdp:discover\"", StringComparison.OrdinalIgnoreCase)) continue;
                if (!headers.TryGetValue("ST", out var st)) continue;
                // A single delayed response task is bounded by the receive loop: no task per UDP packet.
                var mx = headers.TryGetValue("MX", out var mxText) && int.TryParse(mxText, out var parsed) ? Math.Clamp(parsed, 1, 5) : 1;
                await Task.Delay(Random.Shared.Next(0, mx * 1000), stoppingToken);
                foreach (var target in Targets.Where(t => st == "ssdp:all" || st == t))
                {
                    if (!library.Config.Enabled) break;
                    var response = $"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=120\r\nDATE: {DateTime.UtcNow:R}\r\nEXT:\r\nLOCATION: {options.BaseUrl}/device.xml\r\nSERVER: Windows/10.0 UPnP/1.0 LibraryShare/0.1\r\nST: {target}\r\nUSN: {Usn(target)}\r\n\r\n";
                    await Send(response, received.RemoteEndPoint, stoppingToken);
                }
            }
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
        finally
        {
            library.Changed -= OnChanged;
            workerLifetime.Cancel();
            await announcements;
            if (library.Config.Enabled) await Notify(false, CancellationToken.None);
            socket.Dispose(); socket = null;
        }
    }

    private void OnChanged() => _ = Notify(library.Config.Enabled, CancellationToken.None);

    private async Task AnnounceLoop(CancellationToken cancellation)
    {
        try
        {
            await Task.Delay(500, cancellation);
            while (!cancellation.IsCancellationRequested)
            {
                if (library.Config.Enabled) await Notify(true, cancellation);
                await Task.Delay(TimeSpan.FromSeconds(45), cancellation);
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
    }

    private async Task Notify(bool alive, CancellationToken cancellation)
    {
        foreach (var target in Targets)
        {
            var extra = alive ? $"CACHE-CONTROL: max-age=120\r\nLOCATION: {options.BaseUrl}/device.xml\r\nSERVER: Windows/10.0 UPnP/1.0 LibraryShare/0.1\r\n" : "";
            await Send($"NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nNT: {target}\r\nNTS: ssdp:{(alive ? "alive" : "byebye")}\r\nUSN: {Usn(target)}\r\n{extra}\r\n", Multicast, cancellation);
        }
    }

    private async Task Send(string message, IPEndPoint endpoint, CancellationToken cancellation)
    {
        await sending.WaitAsync(cancellation);
        try
        {
            if (socket is not null) await socket.SendAsync(Encoding.ASCII.GetBytes(message), endpoint, cancellation);
        }
        catch (Exception e) when (e is SocketException or ObjectDisposedException)
        { logger.LogDebug("SSDP send failed: {Message}", e.Message); }
        finally { sending.Release(); }
    }
}
