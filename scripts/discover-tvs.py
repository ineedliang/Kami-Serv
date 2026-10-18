"""Read-only Roku SSDP discovery. Does not power on or control a TV."""
import ipaddress
import json
import pathlib
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(("192.0.2.1", 9))  # Route selection only, no datagram sent.
        address = route.getsockname()[0]
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as search:
        search.bind((address, 0))
        search.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(address))
        search.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        search.settimeout(0.5)
        packet = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
                  'MAN: "ssdp:discover"\r\nMX: 2\r\nST: roku:ecp\r\n\r\n').encode("ascii")
        for _ in range(3):
            search.sendto(packet, ("239.255.255.250", 1900))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                response, remote = search.recvfrom(8192)
            except socket.timeout:
                continue
            headers = {}
            for line in response.decode("ascii", "replace").split("\r\n")[1:]:
                key, separator, value = line.partition(":")
                if separator:
                    headers[key.lower()] = value.strip()
            location = headers.get("location", "")
            parsed = urllib.parse.urlsplit(location)
            # Follow only same-device, literal, private IPv4 HTTP endpoints.
            if parsed.scheme != "http" or parsed.hostname != remote[0] or not ipaddress.ip_address(remote[0]).is_private:
                continue
            found[remote[0]] = {"address": remote[0], "endpoint": location}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for device in found.values():
        base = device["endpoint"].rstrip("/")
        for route, key in (("query/device-info", "model"), ("query/active-app", "active_app"),
                           ("query/media-player", "playback"), ("query/apps", "media_player_app")):
            try:
                with opener.open(base + "/" + route, timeout=3) as response:
                    xml = ET.fromstring(response.read(65536))
                if key == "model":
                    device[key] = xml.findtext("model-name")
                    device["name"] = xml.findtext("friendly-device-name") or xml.findtext("user-device-name")
                elif key == "active_app":
                    device[key] = xml.findtext("app")
                elif key == "playback":
                    device[key] = {"state": xml.attrib.get("state"), "error": xml.attrib.get("error"),
                                   "position": xml.findtext("position"), "duration": xml.findtext("duration"),
                                   "format": xml.find("format").attrib if xml.find("format") is not None else None}
                else:
                    device[key] = [{"id": app.attrib.get("id"), "name": app.text}
                                  for app in xml.findall("app") if "media player" in (app.text or "").lower()]
            except (OSError, ValueError, ET.ParseError) as error:
                device[key + "_error"] = str(error)
    output = {"computer_address": address, "devices": list(found.values())}
    path = pathlib.Path(__file__).resolve().parents[1] / "build" / "tv-discovery.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
