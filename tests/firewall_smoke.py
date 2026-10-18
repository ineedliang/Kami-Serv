"""Actual local API and VLC callbacks, with the elevation command replaced by a stub.

The rule engine is separately tested in firewall_rules.ps1. No firewall changes
or UAC prompts occur in this test.
"""
import os
import pathlib
import shutil
import subprocess
import time
import uuid

from integration import Integration, ROOT
from libvlc_smoke import lua_api


def main():
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'tests/firewall_rules.ps1')], check=True)
    project = ROOT / 'build' / ('firewall-check-' + uuid.uuid4().hex[:8])
    (project / 'vlc').mkdir(parents=True)
    (project / 'scripts').mkdir()
    shutil.copyfile(ROOT / 'vlc/library_share.lua', project / 'vlc/library_share.lua')
    mode = project / 'mode.txt'
    mode.write_text('hold')
    (project / 'scripts/configure-firewall.ps1').write_text('''param([string]$Action,[string]$ProgramPath,[int]$Port)
$root=Split-Path -Parent $PSScriptRoot
@{Action=$Action;Program=$ProgramPath;Port=$Port}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $root 'arguments.json')
$mode=(Get-Content -LiteralPath (Join-Path $root 'mode.txt') -Raw).Trim()
if($mode -eq 'hold'){while(-not (Test-Path -LiteralPath (Join-Path $root 'release.txt'))){Start-Sleep -Milliseconds 50}}
if($mode -eq 'fail'){Write-Output 'invalid result';exit 1}
if($mode -eq 'cancel'){@{State='cancelled';Message='Firewall permission cancelled.'}|ConvertTo-Json -Compress;return}
@{State='configured';Message='Private network rules verified (test stub).'}|ConvertTo-Json -Compress
''', encoding='utf-8')
    previous = os.environ.get('LIBRARY_SHARE_TEST_PROJECT')
    os.environ['LIBRARY_SHARE_TEST_PROJECT'] = str(project)
    Integration.setUpClass()
    test = Integration()
    def finish():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = test.control('firewall-wait')
            if result.findtext('firewallActive') == 'false': return result
        raise AssertionError('Firewall operation did not finish')
    try:
        test.enable()
        assert test.control('firewall-allow').findtext('firewallActive') == 'true'
        assert test.control('firewall-check').tag == 'error'
        started = time.monotonic()
        test.control('status')
        assert time.monotonic() - started < .5, 'Firewall permission blocked helper'
        (project / 'release.txt').write_text('release')
        assert finish().findtext('firewallState') == 'configured'
        import json
        arguments = json.loads((project / 'arguments.json').read_text(encoding='utf-8-sig'))
        assert arguments['Action'] == 'Allow' and arguments['Port'] == test.port
        assert pathlib.Path(arguments['Program']).name.lower() == 'dotnet.exe'
        mode.write_text('cancel')
        test.control('firewall-allow')
        assert finish().findtext('firewallState') == 'cancelled'
        mode.write_text('fail')
        test.control('firewall-check')
        assert finish().findtext('firewallState') == 'failed'
        mode.write_text('success')
        lua_api(pathlib.Path(os.environ.get('VLC_DIR', r'C:\Program Files\VideoLAN\VLC')), test, firewall_tests=True)
        print('PASS: authenticated async firewall API, duplicate prevention, cancellation/failure, actual VLC buttons preserve unsaved fields (elevation stubbed)')
    finally:
        Integration.tearDownClass()
        if previous is None: os.environ.pop('LIBRARY_SHARE_TEST_PROJECT', None)
        else: os.environ['LIBRARY_SHARE_TEST_PROJECT'] = previous


if __name__ == '__main__': main()
