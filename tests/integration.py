"""Network-level checks against the real helper. Python standard library only.

Fixtures contain deterministic bytes, not playable video. libvlc_smoke.py tests
actual playback separately. All generated content stays inside build/.
"""
import concurrent.futures
import http.client
import http.server
import json
import os
import pathlib
import re
import socket
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
CONTENT = "urn:schemas-upnp-org:service:ContentDirectory:1"
CONNECTION = "urn:schemas-upnp-org:service:ConnectionManager:1"
DIDL = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT / "build" / ("integration-" + uuid.uuid4().hex[:8])
        cls.media = cls.work / "media"
        cls.media.mkdir(parents=True)
        cls.content = bytes(range(256)) * 65536  # 16 MiB to keep transfers open together.
        (cls.media / "A & B.mp4").write_bytes(cls.content)
        (cls.media / "Second.mkv").write_bytes(b"second-file" * 100)
        (cls.media / "private.txt").write_text("must not be served")
        nested = cls.media / "Nested"
        nested.mkdir()
        (nested / "Third.mp3").write_bytes(b"nested-audio" * 100)
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.log = (cls.work / "server.log").open("w")
        cls.process = subprocess.Popen([
            "dotnet", os.environ.get("LIBRARY_SHARE_TEST_SERVER", str(ROOT / "build/server/LibraryShare.Server.dll")),
            "--project", os.environ.get("LIBRARY_SHARE_TEST_PROJECT", str(ROOT)), "--config", str(cls.work / "config.json"),
            "--extension-dir", str(cls.work / "extension"),
            "--port", str(cls.port), "--no-ssdp", "false",
        ], cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            module = cls.work / "extension/modules/library_share_config.lua"
            if module.exists():
                cls.token = re.search(r'token = "([A-F0-9]+)"', module.read_text())[1]
                break
            if cls.process.poll() is not None:
                cls.log.close()
                raise RuntimeError((cls.work / "server.log").read_text())
            time.sleep(0.05)
        else:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            raise RuntimeError("Helper did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.log.close()

    def control(self, action="status", **kwargs):
        params = urllib.parse.urlencode(dict(token=self.token, action=action, **kwargs))
        with urllib.request.urlopen(self.base + "/local?" + params, timeout=10) as response:
            return ET.fromstring(response.read())

    def soap(self, action, arguments=None, service="content", expect=200):
        namespace = CONTENT if service == "content" else CONNECTION
        envelope = ET.Element(ET.QName(SOAP, "Envelope"))
        body = ET.SubElement(envelope, ET.QName(SOAP, "Body"))
        command = ET.SubElement(body, ET.QName(namespace, action))
        for key, value in (arguments or {}).items():
            ET.SubElement(command, key).text = str(value)
        request = urllib.request.Request(self.base + f"/upnp/{service}/control", data=ET.tostring(envelope),
            headers={"Content-Type": "text/xml", "SOAPAction": f'"{namespace}#{action}"'})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, expect)
            return ET.fromstring(response.read())

    def browse(self, object_id="0", flag="BrowseDirectChildren", start=0, count=0, sort=""):
        result = self.soap("Browse", dict(ObjectID=object_id, BrowseFlag=flag, Filter="*",
            StartingIndex=start, RequestedCount=count, SortCriteria=sort))
        items = ET.fromstring(next(result.iter("Result")).text)
        return list(items), int(next(result.iter("TotalMatches")).text)

    def enable(self):
        self.control("add", folder=str(self.media))
        self.control("enable")
        roots, _ = self.browse()
        return roots[0].attrib["id"]

    def media_url(self, title="A & B.mp4"):
        root_id = self.enable()
        entries, _ = self.browse(root_id)
        item = next(e for e in entries if e.find("{http://purl.org/dc/elements/1.1/}title").text == title)
        return item.find(f"{{{DIDL}}}res").text

    def test_01_off_by_default_and_control_auth(self):
        self.assertIn("Sharing: OFF", self.control().findtext("summary"))
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base + "/local?action=enable")
        self.assertEqual(error.exception.code, 403)
        request = urllib.request.Request(self.base + "/local?token=" + self.token, headers={"Host": "attacker.invalid"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)

    def test_02_descriptions_and_browse_pagination(self):
        for path in ("/device.xml", "/upnp/content.xml", "/upnp/connection.xml"):
            with urllib.request.urlopen(self.base + path) as response:
                ET.fromstring(response.read())
        root_id = self.enable()
        items, total = self.browse(root_id)
        self.assertEqual(total, 3)  # Two media files and one folder; private.txt excluded.
        first, total = self.browse(root_id, count=1, sort="+dc:title")
        second, _ = self.browse(root_id, start=1, count=1, sort="+dc:title")
        self.assertEqual(len(first), 1)
        self.assertNotEqual(first[0].attrib["id"], second[0].attrib["id"])
        metadata, _ = self.browse(first[0].attrib["id"], flag="BrowseMetadata")
        self.assertEqual(metadata[0].attrib["id"], first[0].attrib["id"])
        for item in items:
            resource = item.find(f"{{{DIDL}}}res")
            if resource is not None:
                self.assertIn("DLNA.ORG_OP=01", resource.attrib["protocolInfo"])
                self.assertNotIn(str(self.media), resource.text)

    def test_03_head_ranges_and_resume(self):
        url = self.media_url()
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(int(response.headers["Content-Length"]), len(self.content))
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.read(), b"")
        for header, start, end in (("bytes=5000-5999", 5000, 6000), ("bytes=0-999", 0, 1000),
                                   ("bytes=-128", len(self.content)-128, len(self.content))):
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": header})) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), self.content[start:end])
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url, headers={"Range": f"bytes={len(self.content)}-"}))
        self.assertEqual(error.exception.code, 416)

    def test_04_four_overlapping_independent_transfers(self):
        url = self.media_url()
        path = urllib.parse.urlsplit(url).path
        barrier = threading.Barrier(5)
        def download(index):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            connection.connect()
            connection.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            start = index * 65536
            connection.request("GET", path, headers={"Range": f"bytes={start}-"})
            response = connection.getresponse()
            self.assertEqual(response.status, 206)
            barrier.wait(timeout=10)
            barrier.wait(timeout=10)
            data = response.read(8192)
            connection.close()
            return data, start
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [pool.submit(download, i) for i in range(4)]
            barrier.wait(timeout=10)
            try:
                status = self.control()
                self.assertGreaterEqual(len(status.findall("transfers/transfer")), 4)
            finally:
                barrier.wait(timeout=10)
            for job in jobs:
                data, start = job.result(timeout=10)
                self.assertEqual(data, self.content[start:start+8192])

    def test_05_soap_faults_and_connection_info(self):
        self.enable()
        result = self.soap("GetProtocolInfo", service="connection")
        self.assertIn("video/mp4", next(result.iter("Source")).text)
        self.soap("GetCurrentConnectionInfo", {"ConnectionID": 0}, service="connection")
        result = self.soap("Browse", dict(ObjectID="missing", BrowseFlag="BrowseMetadata", Filter="*",
            StartingIndex=0, RequestedCount=1, SortCriteria=""), expect=500)
        self.assertEqual(next(result.iter("errorCode")).text, "701")
        self.soap("UnknownAction", expect=500)

    def test_06_remove_and_disable_revoke_urls(self):
        url = self.media_url()
        self.control("remove", folder=str(self.media))
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url)
        self.assertEqual(error.exception.code, 404)
        url = self.media_url()
        self.control("disable")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url)
        self.assertEqual(error.exception.code, 503)

    def test_07_event_subscription_and_initial_state(self):
        self.enable()
        received = threading.Event()
        notifications = []
        class Callback(http.server.BaseHTTPRequestHandler):
            def do_NOTIFY(self):
                notifications.append((dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                received.set()
            def log_message(self, *_):
                pass
        callback = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Callback)
        thread = threading.Thread(target=callback.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            route = "/upnp/content/event"
            connection.request("SUBSCRIBE", route, headers={"CALLBACK": f"<http://127.0.0.1:{callback.server_port}/events>",
                "NT": "upnp:event", "TIMEOUT": "Second-60"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            sid = response.headers["SID"]
            response.read()
            self.assertTrue(received.wait(5), "Initial GENA notification missing")
            self.assertIn(b"SystemUpdateID", notifications[0][1])
            self.assertEqual(notifications[0][0]["SEQ"], "0")
            received.clear()
            self.control("rescan")
            self.assertTrue(received.wait(5), "Library update notification missing")
            connection.request("SUBSCRIBE", route, headers={"SID": sid, "TIMEOUT": "Second-120"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            connection.request("UNSUBSCRIBE", route, headers={"SID": sid})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            connection.close()
            # Callback URLs must point to the subscribing client, using a literal IP.
            connection = http.client.HTTPConnection("127.0.0.1", self.port)
            connection.request("SUBSCRIBE", route, headers={"CALLBACK": "<http://192.168.1.254/admin>", "NT": "upnp:event"})
            response = connection.getresponse()
            self.assertEqual(response.status, 412)
            response.read()
            connection.close()
        finally:
            callback.shutdown()
            callback.server_close()

    def test_08_ssdp_search(self):
        self.enable()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as search:
            search.bind(("127.0.0.1", 0))
            search.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
            search.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            search.settimeout(3)
            message = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
                'MAN: "ssdp:discover"\r\nMX: 1\r\nST: urn:schemas-upnp-org:device:MediaServer:1\r\n\r\n')
            search.sendto(message.encode("ascii"), ("239.255.255.250", 1900))
            response, _ = search.recvfrom(8192)
            self.assertIn((self.base + "/device.xml").encode(), response)
            self.assertIn(b"HTTP/1.1 200 OK", response)

    def test_09_unknown_and_unshared_paths(self):
        self.enable()
        for path in ("/media/not-an-id/private.txt", "/config.json", "/vlc/library_share.lua", "/media/../../private.txt"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)
        error = self.control("add", folder=str(self.work / "missing"))
        self.assertEqual(error.tag, "error")

    def test_10_labels_filters_identity_and_preferences(self):
        self.enable()
        try:
            response = self.control("add", folder=str(self.media), label="My music & radio", mediaType="audio")
            roots, _ = self.browse()
            self.assertEqual(roots[0].findtext("{http://purl.org/dc/elements/1.1/}title"), "My music & radio")
            children, _ = self.browse(roots[0].attrib["id"])
            self.assertFalse(any(c.tag.endswith("item") for c in children))
            nested, _ = self.browse(children[0].attrib["id"])
            self.assertEqual(len(nested), 1)
            self.control("identity", name="Charlie's TV & music")
            with urllib.request.urlopen(self.base + "/device.xml") as response:
                description = ET.fromstring(response.read())
            ns = "{urn:schemas-upnp-org:device-1-0}"
            self.assertEqual(description.findtext(f"{ns}device/{ns}friendlyName"), "Charlie's TV & music")
            settings = dict(audio="aac", position="file", offset="35", font="Arial", size="32", bold="true", color="FFFF00", outline="3")
            status = self.control("settings", **settings)
            self.assertEqual(status.findtext("fontSize"), "32")
            self.assertEqual(status.findtext("audioPreference"), "aac")
            self.assertEqual(self.control("settings", **dict(settings, size="0")).tag, "error")
            saved = json.loads((self.work / "config.json.playback.json").read_text())
            self.assertEqual(saved["FontSize"], 32)
            self.assertEqual(self.control("add", folder=str(self.work), label="bad", mediaType="executable").tag, "error")
            self.assertNotIn(str(self.work), [f.text for f in self.control().findall("./folders/folder")])
        finally:
            self.control("add", folder=str(self.media), label="", mediaType="all")

    def test_11_custom_icon_normalization_and_delivery(self):
        import struct
        import zlib
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        image = self.work / "icon ' $test.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"\0\xff\0\0\xff\0\xff\0\xff")) + chunk(b"IEND", b""))
        response = self.control("identity", name="Test icon", icon=str(image))
        self.assertNotEqual(response.tag, "error", response.text)
        with urllib.request.urlopen(self.base + "/server-icon.png") as response:
            content = response.read()
            self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(struct.unpack(">II", content[16:24]), (256, 256))
        with urllib.request.urlopen(self.base + "/device.xml") as response:
            self.assertIn(b"/server-icon.png", response.read())
        self.control("identity", name="Test icon", clearIcon="true")
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(self.base + "/server-icon.png")
        self.assertEqual(missing.exception.code, 404)

    def test_12_short_transfers_remain_visible_after_completion(self):
        url = self.media_url()
        def recent(method, status):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                snapshot = self.control()
                rows = [t.text for t in snapshot.findall("./recentTransfers/recentTransfer")]
                matches = [row for row in rows if "A & B.mp4" in row and f"{method} HTTP {status}" in row]
                if matches:
                    self.assertIn("RECENT", matches[0])
                    self.assertIn("127.0.0.1", matches[0])
                    return snapshot, matches[0]
                time.sleep(.02)
            self.fail(f"Finished {method} {status} request was lost between refreshes")
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:
            response.read()
        recent("HEAD", 200)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-31"})) as response:
            self.assertEqual(response.read(), self.content[:32])
        snapshot, row = recent("GET", 206)
        self.assertIn("bytes=0-31", row)
        self.assertEqual(snapshot.findall("./transfers/transfer"), [])
        # Refresh must retain this entry, without presenting it as active playback.
        self.assertTrue(any("A & B.mp4" in r.text for r in self.control().findall("./recentTransfers/recentTransfer")))
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=999999999-"}))
        recent("GET", 416)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(self.base + "/local?action=status")
        self.assertEqual(denied.exception.code, 403)

    def test_13_recent_activity_is_bounded_and_coalesces_requests(self):
        for i in range(55):
            (self.media / f"History {i:02}.mp4").write_bytes(b"fixture")
        root = self.enable()
        entries, _ = self.browse(root)
        urls = [item.find(f"{{{DIDL}}}res").text for item in entries
            if item.findtext("{http://purl.org/dc/elements/1.1/}title", "").startswith("History ")]
        for url in urls:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:
                response.read()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            rows = self.control().findall("./recentTransfers/recentTransfer")
            if len(rows) == 50 and any("History 54" in r.text for r in rows): break
            time.sleep(.02)
        self.assertEqual(len(rows), 50)
        for _ in range(3):
            with urllib.request.urlopen(urllib.request.Request(urls[-1], method="HEAD")) as response:
                response.read()
        self.assertEqual(len(self.control().findall("./recentTransfers/recentTransfer")), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
