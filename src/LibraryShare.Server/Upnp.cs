using System.Xml;
using System.Xml.Linq;

namespace LibraryShare;

public sealed class UpnpFault(int code, string message) : Exception(message)
{
    public int Code { get; } = code;
}

public static class Upnp
{
    public const string ContentDirectory = "urn:schemas-upnp-org:service:ContentDirectory:1";
    public const string ConnectionManager = "urn:schemas-upnp-org:service:ConnectionManager:1";
    public const string MediaServer = "urn:schemas-upnp-org:device:MediaServer:1";
    public const string Features = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000";
    private static readonly XNamespace Soap = "http://schemas.xmlsoap.org/soap/envelope/";
    private static readonly XNamespace Device = "urn:schemas-upnp-org:device-1-0";
    private static readonly XNamespace Service = "urn:schemas-upnp-org:service-1-0";
    private static readonly XNamespace Didl = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/";
    private static readonly XNamespace Dc = "http://purl.org/dc/elements/1.1/";
    private static readonly XNamespace Metadata = "urn:schemas-upnp-org:metadata-1-0/upnp/";

    public static string Protocol(string mime) => $"http-get:*:{mime}:{Features}";
    public static string Protocols => string.Join(',', Library.Formats.Values.Select(v => v.Mime).Distinct().Select(Protocol));
    public static string Xml(XElement element) => "<?xml version=\"1.0\" encoding=\"utf-8\"?>" + element.ToString(SaveOptions.DisableFormatting);

    public static string Description(ShareConfig config) => Xml(new XElement(Device + "root",
        new XElement(Device + "specVersion", new XElement(Device + "major", 1), new XElement(Device + "minor", 0)),
        new XElement(Device + "device",
            new XElement(Device + "deviceType", MediaServer), new XElement(Device + "friendlyName", config.Name),
            new XElement(Device + "manufacturer", "Library Share Project"),
            new XElement(Device + "modelDescription", "VLC Library Share development prototype"),
            new XElement(Device + "modelName", "Library Share"), new XElement(Device + "modelNumber", "0.2"),
            new XElement(Device + "UDN", $"uuid:{config.Id}"),
            config.Icon is not { } icon ? null : new XElement(Device + "iconList", new XElement(Device + "icon",
                new XElement(Device + "mimetype", icon.Mime), new XElement(Device + "width", icon.Width),
                new XElement(Device + "height", icon.Height), new XElement(Device + "depth", icon.Depth),
                new XElement(Device + "url", "/server-icon.png?v=" + Path.GetFileNameWithoutExtension(icon.File)))),
            new XElement(Device + "serviceList", ServiceDescription("content", ContentDirectory, "ContentDirectory"),
                ServiceDescription("connection", ConnectionManager, "ConnectionManager")))));

    private static XElement ServiceDescription(string route, string type, string id) => new(Device + "service",
        new XElement(Device + "serviceType", type), new XElement(Device + "serviceId", "urn:upnp-org:serviceId:" + id),
        new XElement(Device + "SCPDURL", $"/upnp/{route}.xml"),
        new XElement(Device + "controlURL", $"/upnp/{route}/control"),
        new XElement(Device + "eventSubURL", $"/upnp/{route}/event"));

    // Each action's arguments refer to a declared state variable, as required by UPnP SCPD.
    public static string Scpd(string service)
    {
        var actions = new List<XElement>();
        var states = new Dictionary<string, (string Type, bool Events)>();
        void Action(string name, params (string Name, string Direction, string State, string Type, bool Events)[] args)
        {
            foreach (var arg in args) states[arg.State] = (arg.Type, arg.Events);
            actions.Add(new XElement(Service + "action", new XElement(Service + "name", name), args.Length == 0 ? null :
                new XElement(Service + "argumentList", args.Select(a => new XElement(Service + "argument",
                    new XElement(Service + "name", a.Name), new XElement(Service + "direction", a.Direction),
                    new XElement(Service + "relatedStateVariable", a.State))))));
        }
        if (service == "content")
        {
            Action("Browse", ("ObjectID", "in", "A_ARG_TYPE_ObjectID", "string", false),
                ("BrowseFlag", "in", "A_ARG_TYPE_BrowseFlag", "string", false),
                ("Filter", "in", "A_ARG_TYPE_Filter", "string", false),
                ("StartingIndex", "in", "A_ARG_TYPE_Index", "ui4", false),
                ("RequestedCount", "in", "A_ARG_TYPE_Count", "ui4", false),
                ("SortCriteria", "in", "A_ARG_TYPE_SortCriteria", "string", false),
                ("Result", "out", "A_ARG_TYPE_Result", "string", false),
                ("NumberReturned", "out", "A_ARG_TYPE_Count", "ui4", false),
                ("TotalMatches", "out", "A_ARG_TYPE_Count", "ui4", false),
                ("UpdateID", "out", "SystemUpdateID", "ui4", true));
            Action("GetSearchCapabilities", ("SearchCaps", "out", "SearchCapabilities", "string", false));
            Action("GetSortCapabilities", ("SortCaps", "out", "SortCapabilities", "string", false));
            Action("GetSystemUpdateID", ("Id", "out", "SystemUpdateID", "ui4", true));
        }
        else
        {
            Action("GetProtocolInfo", ("Source", "out", "SourceProtocolInfo", "string", true),
                ("Sink", "out", "SinkProtocolInfo", "string", true));
            Action("GetCurrentConnectionIDs", ("ConnectionIDs", "out", "CurrentConnectionIDs", "string", true));
            Action("GetCurrentConnectionInfo", ("ConnectionID", "in", "A_ARG_TYPE_ConnectionID", "i4", false),
                ("RcsID", "out", "A_ARG_TYPE_RcsID", "i4", false), ("AVTransportID", "out", "A_ARG_TYPE_AVTransportID", "i4", false),
                ("ProtocolInfo", "out", "A_ARG_TYPE_ProtocolInfo", "string", false),
                ("PeerConnectionManager", "out", "A_ARG_TYPE_ConnectionManager", "string", false),
                ("PeerConnectionID", "out", "A_ARG_TYPE_ConnectionID", "i4", false),
                ("Direction", "out", "A_ARG_TYPE_Direction", "string", false),
                ("Status", "out", "A_ARG_TYPE_ConnectionStatus", "string", false));
        }
        return Xml(new XElement(Service + "scpd", new XElement(Service + "specVersion",
            new XElement(Service + "major", 1), new XElement(Service + "minor", 0)),
            new XElement(Service + "actionList", actions),
            new XElement(Service + "serviceStateTable", states.Select(s => new XElement(Service + "stateVariable",
                new XAttribute("sendEvents", s.Value.Events ? "yes" : "no"),
                new XElement(Service + "name", s.Key), new XElement(Service + "dataType", s.Value.Type),
                s.Key == "A_ARG_TYPE_BrowseFlag" ? new XElement(Service + "allowedValueList",
                    new XElement(Service + "allowedValue", "BrowseMetadata"), new XElement(Service + "allowedValue", "BrowseDirectChildren")) : null)))));
    }

    public static async Task<XElement> ReadAction(HttpRequest request, CancellationToken cancellation)
    {
        using var reader = XmlReader.Create(request.Body, new XmlReaderSettings
        { Async = true, DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 65536 });
        var envelope = await XElement.LoadAsync(reader, LoadOptions.None, cancellation);
        return envelope.Element(Soap + "Body")?.Elements().SingleOrDefault() ?? throw new UpnpFault(402, "Invalid Args");
    }

    public static string Respond(string service, XElement action, Library library, string baseUrl)
    {
        var expected = service == "content" ? ContentDirectory : ConnectionManager;
        if (action.Name.NamespaceName != expected) throw new UpnpFault(401, "Invalid Action");
        var output = new List<XElement>();
        void Out(string name, object value) => output.Add(new XElement(name, value));
        string Arg(string name) => action.Element(name)?.Value ?? throw new UpnpFault(402, "Invalid Args");
        var snapshot = library.Snapshot;
        switch (action.Name.LocalName)
        {
            case "Browse" when service == "content":
                var id = Arg("ObjectID");
                if (!snapshot.Entries.TryGetValue(id, out var entry)) throw new UpnpFault(701, "No Such Object");
                if (!uint.TryParse(Arg("StartingIndex"), out var start) || !uint.TryParse(Arg("RequestedCount"), out var count))
                    throw new UpnpFault(402, "Invalid Args");
                _ = Arg("Filter");
                var sort = Arg("SortCriteria");
                if (sort is not ("" or "+dc:title" or "-dc:title")) throw new UpnpFault(709, "Unsupported Sort Criteria");
                var browseFlag = Arg("BrowseFlag");
                IEnumerable<MediaEntry> items = browseFlag switch
                {
                    "BrowseMetadata" => [entry],
                    "BrowseDirectChildren" when entry.IsFolder => snapshot.Entries.Values.Where(e => e.Parent == id),
                    "BrowseDirectChildren" => throw new UpnpFault(710, "No Such Container"),
                    _ => throw new UpnpFault(402, "Invalid Args")
                };
                items = sort == "-dc:title" ? items.OrderByDescending(e => e.Title, StringComparer.OrdinalIgnoreCase)
                    : items.OrderBy(e => e.Title, StringComparer.OrdinalIgnoreCase);
                var all = items.ToArray();
                var page = browseFlag == "BrowseMetadata" ? all : all.Skip((int)Math.Min(start, int.MaxValue))
                    .Take(count == 0 ? int.MaxValue : (int)Math.Min(count, int.MaxValue)).ToArray();
                Out("Result", new XElement(Didl + "DIDL-Lite", new XAttribute(XNamespace.Xmlns + "dc", Dc),
                    new XAttribute(XNamespace.Xmlns + "upnp", Metadata), page.Select(e => DidlEntry(e, snapshot, baseUrl))).ToString(SaveOptions.DisableFormatting));
                Out("NumberReturned", page.Length); Out("TotalMatches", all.Length); Out("UpdateID", snapshot.UpdateId);
                break;
            case "GetSearchCapabilities" when service == "content": Out("SearchCaps", ""); break;
            case "GetSortCapabilities" when service == "content": Out("SortCaps", "dc:title"); break;
            case "GetSystemUpdateID" when service == "content": Out("Id", snapshot.UpdateId); break;
            case "GetProtocolInfo" when service == "connection": Out("Source", Protocols); Out("Sink", ""); break;
            case "GetCurrentConnectionIDs" when service == "connection": Out("ConnectionIDs", "0"); break;
            case "GetCurrentConnectionInfo" when service == "connection":
                if (Arg("ConnectionID") != "0") throw new UpnpFault(706, "Invalid Connection Reference");
                Out("RcsID", -1); Out("AVTransportID", -1); Out("ProtocolInfo", "");
                Out("PeerConnectionManager", ""); Out("PeerConnectionID", -1); Out("Direction", "Output"); Out("Status", "OK"); break;
            default: throw new UpnpFault(401, "Invalid Action");
        }
        return Envelope(new XElement(XName.Get(action.Name.LocalName + "Response", expected), output));
    }

    private static XElement DidlEntry(MediaEntry entry, LibrarySnapshot snapshot, string baseUrl)
    {
        var element = new XElement(Didl + (entry.IsFolder ? "container" : "item"),
            new XAttribute("id", entry.Id), new XAttribute("parentID", entry.Parent), new XAttribute("restricted", "1"),
            new XElement(Dc + "title", entry.Title), new XElement(Metadata + "class", entry.MediaClass));
        if (entry.IsFolder) element.Add(new XAttribute("childCount", snapshot.Entries.Values.Count(e => e.Parent == entry.Id)));
        else element.Add(new XElement(Didl + "res", new XAttribute("protocolInfo", Protocol(entry.Mime!)),
            new XAttribute("size", entry.Size), $"{baseUrl}/media/{entry.Id}/{Uri.EscapeDataString(entry.Title)}"));
        return element;
    }

    private static string Envelope(XElement body) => Xml(new XElement(Soap + "Envelope",
        new XAttribute(XNamespace.Xmlns + "s", Soap), new XAttribute(Soap + "encodingStyle", "http://schemas.xmlsoap.org/soap/encoding/"),
        new XElement(Soap + "Body", body)));

    public static string Fault(int code, string message) => Envelope(new XElement(Soap + "Fault",
        new XElement("faultcode", "s:Client"), new XElement("faultstring", "UPnPError"),
        new XElement("detail", new XElement(XName.Get("UPnPError", "urn:schemas-upnp-org:control-1-0"),
            new XElement("errorCode", code), new XElement("errorDescription", message)))));
}
