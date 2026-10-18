using System.Collections.Concurrent;
using System.Net;
using System.Xml.Linq;

namespace LibraryShare;

// Minimal GENA subscriptions: initial state and updates after a library change.
// Notifications may only go back to the subscribing device, never an arbitrary URL.
public sealed class Events(Library library, ILogger<Events> logger) : IDisposable
{
    private sealed class Subscription(string route, Uri callback, IPAddress owner, int timeout)
    {
        public string Route { get; } = route;
        public Uri Callback { get; } = callback;
        public IPAddress Owner { get; } = owner;
        public DateTime Expires { get; set; } = DateTime.UtcNow.AddSeconds(timeout);
        public uint Sequence { get; set; }
        public SemaphoreSlim Gate { get; } = new(1, 1);
    }
    private readonly ConcurrentDictionary<string, Subscription> subscriptions = new();
    private readonly HttpClient client = new(new SocketsHttpHandler
    { AllowAutoRedirect = false, UseProxy = false, ConnectTimeout = TimeSpan.FromSeconds(2) })
    { Timeout = TimeSpan.FromSeconds(3) };

    public void Start() => library.Changed += Changed;

    public IResult Handle(HttpContext context, string route)
    {
        foreach (var old in subscriptions.Where(s => s.Value.Expires <= DateTime.UtcNow)) subscriptions.TryRemove(old.Key, out _);
        var request = context.Request;
        var owner = context.Connection.RemoteIpAddress!.MapToIPv4();
        var sid = request.Headers["SID"].ToString();
        if (request.Method == "UNSUBSCRIBE")
        {
            if (!subscriptions.TryGetValue(sid, out var old) || !old.Owner.Equals(owner) || old.Route != route) return Results.StatusCode(412);
            subscriptions.TryRemove(sid, out _);
            return Results.Ok();
        }
        var timeoutText = request.Headers["TIMEOUT"].ToString();
        var timeout = timeoutText.StartsWith("Second-", StringComparison.OrdinalIgnoreCase) && int.TryParse(timeoutText[7..], out var seconds)
            ? Math.Clamp(seconds, 30, 1800) : 1800;
        if (sid.Length > 0)
        {
            if (request.Headers.ContainsKey("CALLBACK") || request.Headers.ContainsKey("NT") ||
                !subscriptions.TryGetValue(sid, out var old) || !old.Owner.Equals(owner) || old.Route != route) return Results.StatusCode(412);
            old.Expires = DateTime.UtcNow.AddSeconds(timeout);
        }
        else
        {
            if (subscriptions.Count >= 128) return Results.StatusCode(503);
            var callbackText = request.Headers["CALLBACK"].ToString();
            if (request.Headers["NT"] != "upnp:event" || !callbackText.StartsWith('<') || !callbackText.EndsWith('>') ||
                !Uri.TryCreate(callbackText[1..^1], UriKind.Absolute, out var callback) ||
                callback.Scheme != "http" || callback.UserInfo.Length > 0 ||
                !IPAddress.TryParse(callback.Host, out var callbackIp) || !callbackIp.MapToIPv4().Equals(owner)) return Results.StatusCode(412);
            sid = "uuid:" + Guid.NewGuid();
            subscriptions[sid] = new(route, callback, owner, timeout);
            var initialSid = sid;
            context.Response.OnCompleted(() => Notify(initialSid));
        }
        context.Response.Headers["SID"] = sid;
        context.Response.Headers["TIMEOUT"] = $"Second-{timeout}";
        return Results.Ok();
    }

    private void Changed()
    {
        foreach (var sid in subscriptions.Keys) _ = Notify(sid);
    }

    private async Task Notify(string sid)
    {
        if (!subscriptions.TryGetValue(sid, out var subscription)) return;
        await subscription.Gate.WaitAsync();
        try
        {
            if (subscription.Expires < DateTime.UtcNow) { subscriptions.TryRemove(sid, out _); return; }
            XNamespace ns = "urn:schemas-upnp-org:event-1-0";
            var properties = subscription.Route == "content"
                ? new[] { new XElement("SystemUpdateID", library.Snapshot.UpdateId) }
                : [new XElement("SourceProtocolInfo", Upnp.Protocols), new XElement("SinkProtocolInfo", ""), new XElement("CurrentConnectionIDs", "0")];
            var body = new XElement(ns + "propertyset", new XAttribute(XNamespace.Xmlns + "e", ns),
                properties.Select(p => new XElement(ns + "property", p)));
            using var request = new HttpRequestMessage(new HttpMethod("NOTIFY"), subscription.Callback);
            request.Headers.TryAddWithoutValidation("NT", "upnp:event");
            request.Headers.TryAddWithoutValidation("NTS", "upnp:propchange");
            request.Headers.TryAddWithoutValidation("SID", sid);
            request.Headers.TryAddWithoutValidation("SEQ", subscription.Sequence.ToString());
            subscription.Sequence = subscription.Sequence == uint.MaxValue ? 1 : subscription.Sequence + 1;
            request.Content = new StringContent(Upnp.Xml(body), System.Text.Encoding.UTF8, "text/xml");
            using var response = await client.SendAsync(request);
            if (!response.IsSuccessStatusCode) subscriptions.TryRemove(sid, out _);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or ObjectDisposedException)
        { subscriptions.TryRemove(sid, out _); logger.LogDebug("Event callback ended: {Message}", e.Message); }
        finally { subscription.Gate.Release(); }
    }

    public void Dispose() { library.Changed -= Changed; client.Dispose(); }
}
