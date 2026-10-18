"""Exercise installation and VLC's helper-launch button inside the workspace.

Does not install into the user's real VLC profile or open a normal VLC window.
Real headless VLC processes exercise owner shutdown, shared ownership, active
transfer cancellation, and helper bootstrap from VLC's real Lua runtime.
"""
import json
import hashlib
import http.client
import os
import pathlib
import subprocess
import socket
import time
import types
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from integration import ROOT, free_port
from libvlc_smoke import lua_api


def main():
    work = ROOT / "build" / ("install-check-" + uuid.uuid4().hex[:8])
    installed = work / "installed app"
    extension = work / "extension"
    media = work / "media"
    media.mkdir(parents=True)
    fixture = media / "Fixture.mp4"
    fixture.write_bytes(bytes(range(256)) * 65536)
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "scripts/install-vlc-plugin.ps1"), "-Destination", str(installed),
        "-ExtensionDirectory", str(extension), "-NoLaunch"], check=True)
    config = installed / "build/library.json"
    fresh = json.loads(config.read_text(encoding="utf-8-sig"))
    assert not fresh["Enabled"] and not fresh["Folders"], "Fresh install copied development shares"
    assert (extension / "modules/library_share_config.lua").exists(), "Fresh install cannot bootstrap from VLC"
    config.write_text(json.dumps(dict(Enabled=True, Folders=[str(media)])))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def control(action, **parameters):
        token = (installed / "build/library.json.control-token").read_text().strip()
        return opener.open(base + "/local?" + urllib.parse.urlencode(dict(token=token, action=action, **parameters)), timeout=5)
    def status():
        with control("status") as response: return ET.fromstring(response.read())
    def wait_stopped():
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try: status()
            except OSError:
                # HTTP shutdown alone is insufficient: require the actual helper
                # process handle to signal, too.
                helper_pid = int((installed / "build/helper.pid").read_text(encoding="utf-8-sig"))
                import ctypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(0x100000, False, helper_pid)
                if not handle: return
                try:
                    if kernel.WaitForSingleObject(handle, 0) == 0: return
                finally: kernel.CloseHandle(handle)
            time.sleep(.1)
        raise AssertionError("Helper remained alive after VLC closed")
    vlc_dir = pathlib.Path(os.environ.get("VLC_DIR", r"C:\Program Files\VideoLAN\VLC"))
    owners = []
    def owner():
        process = subprocess.Popen([str(vlc_dir / "vlc.exe"), "--no-one-instance", "--ignore-config", "--no-media-library",
            "--no-metadata-network-access", "--config=" + str(work / f"vlc-{len(owners)}.conf"), "--intf=dummy", "--aout=dummy", "--vout=dummy"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        owners.append(process)
        assert process.poll() is None
        return process
    def created(process):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
            f"(Get-Process -Id {process.pid}).StartTime.ToUniversalTime().Ticks"], capture_output=True, text=True, check=True)
        return int(result.stdout.strip())
    stream = None
    try:
        first = owner()
        first_created = created(first)
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(installed / "scripts/launch-helper.ps1"), "-Port", str(port), "-LocalOnly",
            "-OwnerPid", str(first.pid), "-OwnerStarted", str(first_created)], check=True, timeout=15)
        assert status().findtext("vlcOwners") == "1"
        # Reused/mismatched process identities must not attach.
        with control("attach-owner", pid=first.pid, created=first_created+1) as response:
            assert ET.fromstring(response.read()).tag == "error"
        second = owner()
        with control("attach-owner", pid=second.pid, created=created(second)) as response:
            assert ET.fromstring(response.read()).findtext("vlcOwners") == "2"
        first.terminate(); first.wait(timeout=5)
        time.sleep(.6)
        assert status().findtext("vlcOwners") == "1", "Closing one attached instance stopped another's helper"
        identifier = hashlib.sha256(str(fixture.resolve()).upper().encode()).hexdigest()[:32]
        stream = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        stream.connect()
        stream.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        stream.request("GET", f"/media/{identifier}/fixture.mp4".replace(identifier, identifier.upper()))
        response = stream.getresponse()
        assert response.status == 200
        assert status().findall("./transfers/transfer"), "Expected an active transfer before shutdown"
        second.terminate(); second.wait(timeout=5)
        wait_stopped()
        stream.close(); stream = None
        print("PASS: closing the last attached VLC stops the actual helper process, even during an active transfer")
        test = types.SimpleNamespace(work=work, media=media)
        lua_api(vlc_dir, test,
            extension_path=extension / "library_share.lua", bootstrap=True)
        wait_stopped()
        saved = json.loads(config.read_text())
        assert saved["Enabled"] and saved["Folders"], "Closing VLC changed saved share preferences"
        print("PASS: real VLC Lua auto-started/attached its packaged helper; VLC exit stopped it; settings persisted")
        print("Artifacts: " + str(work))
    finally:
        if stream: stream.close()
        try:
            with control("shutdown") as response:
                response.read()
        except OSError:
            pass
        for process in owners:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)


if __name__ == "__main__":
    main()
