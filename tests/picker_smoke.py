"""Chooser process/API/Lua regression checks with a deterministic chooser stub.

The real PowerShell interpreter, helper and VLC Lua HTTP/XML interpreter run.
The native GUI is replaced so checks do not manipulate the user's desktop.
This does not certify native dialog visibility or focus.
"""
import os
import pathlib
import shutil
import time
import uuid

from integration import Integration, ROOT
from libvlc_smoke import lua_api


def main():
    project = ROOT / "build" / ("picker-check-" + uuid.uuid4().hex[:8])
    (project / "vlc").mkdir(parents=True)
    (project / "scripts").mkdir()
    shutil.copyfile(ROOT / "vlc/library_share.lua", project / "vlc/library_share.lua")
    previous = os.environ.get("LIBRARY_SHARE_TEST_PROJECT")
    os.environ["LIBRARY_SHARE_TEST_PROJECT"] = str(project)
    Integration.setUpClass()
    test = Integration()
    mode = project / "mode.txt"
    gate = project / "release.txt"
    selection = project / "selected.txt"
    # Plain UTF-8 result verifies spaces, ampersands and non-ASCII paths through
    # the child-process reader and actual VLC XML decoder.
    unicode_folder = test.media / "Caf\u00e9 & video"
    unicode_folder.mkdir()
    selection.write_text(unicode_folder.as_posix(), encoding="utf-8")
    script = '''param([string]$Kind,[string]$DiagnosticLog)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$root=Split-Path -Parent $PSScriptRoot
$mode=Get-Content -LiteralPath (Join-Path $root 'mode.txt') -Raw
if($mode.Trim() -eq 'fail'){throw 'Intentional chooser launch failure'}
if($mode.Trim() -eq 'cancel'){return}
if($mode.Trim() -eq 'hold'){
 while(-not (Test-Path -LiteralPath (Join-Path $root 'release.txt'))){Start-Sleep -Milliseconds 50}
}
Start-Sleep -Milliseconds 150
$path=[IO.File]::ReadAllText((Join-Path $root 'selected.txt'),[Text.Encoding]::UTF8)
if($Kind -eq 'icon'){$path+='/icon & test.png'}
[Console]::Write($path)
'''
    (project / "scripts/pick-path.ps1").write_text(script, encoding="utf-8")
    def finish():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = test.control("picker-wait")
            if response.findtext("pickerActive") == "false":
                return response
        raise AssertionError("Chooser did not finish")
    try:
        test.enable()
        mode.write_text("hold")
        start = test.control("pick-folder")
        assert start.findtext("pickerActive") == "true"
        assert test.control("pick-icon").tag == "error", "Duplicate chooser was accepted"
        began = time.monotonic()
        test.control("status")
        assert time.monotonic() - began < .5, "Chooser blocked normal helper requests"
        gate.write_text("release")
        result = finish()
        assert result.findtext("pickedFolder") == unicode_folder.as_posix()
        mode.write_text("cancel")
        test.control("pick-folder")
        result = finish()
        assert result.findtext("pickerMessage") == "Selection cancelled."
        assert result.find("pickedFolder") is None
        mode.write_text("fail")
        test.control("pick-folder")
        result = finish()
        assert "Intentional chooser launch failure" in result.findtext("pickerMessage")
        assert result.find("pickedFolder") is None
        mode.write_text("success")
        selection.write_text(test.media.as_posix(), encoding="utf-8")
        lua_api(pathlib.Path(os.environ.get("VLC_DIR", r"C:\Program Files\VideoLAN\VLC")), test, picker_tests=True)
        print("PASS: chooser completion/cancel/failure; duplicate prevention; actual VLC auto-fill preserves unsaved folder/server/playback fields")
    finally:
        Integration.tearDownClass()
        if previous is None:
            os.environ.pop("LIBRARY_SHARE_TEST_PROJECT", None)
        else:
            os.environ["LIBRARY_SHARE_TEST_PROJECT"] = previous


if __name__ == "__main__":
    main()
