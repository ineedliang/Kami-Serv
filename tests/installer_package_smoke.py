"""Extract, install, upgrade and uninstall the actual EXE payload in the workspace.

No live firewall changes, user-profile extensions, registry registration, GUI
interaction, or shortcuts are performed. Registration is left to the interactive
installer; this test exercises its same installation/removal scripts.
"""
import json
import os
import pathlib
import re
import subprocess
import uuid
import zipfile

from integration import ROOT


def run_script(script, *arguments, success=True):
    environment = os.environ.copy()
    environment['PATH'] = os.pathsep.join((str(pathlib.Path(os.environ['WINDIR']) / 'System32'), str(pathlib.Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0'),
        os.environ['WINDIR'], str(pathlib.Path(os.environ['ProgramFiles']) / 'dotnet')))
    powershell = pathlib.Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), *map(str, arguments)], capture_output=True, text=True, encoding='utf-8', env=environment)
    if success and result.returncode != 0: raise AssertionError(result.stdout + result.stderr)
    return result


def main():
    work = ROOT / 'build' / ('setup-check-' + uuid.uuid4().hex[:8])
    work.mkdir(parents=True)
    payload = work / 'Extracted Caf\u00e9 & setup'
    installer = ROOT / 'build/dist/LibraryShare-0.3.0-alpha.1-Setup.exe'
    subprocess.run([str(installer), '--extract-only', str(payload)], check=True, timeout=10)
    assert subprocess.run([str(installer), '--extract-only', str(payload)], timeout=10).returncode != 0, 'Extraction overwrote a nonempty folder'
    files = [p for p in payload.rglob('*') if p.is_file()]
    assert len(files) == 15
    with zipfile.ZipFile(ROOT / 'build/dist/LibraryShare-payload.zip') as archive:
        assert len(archive.infolist()) == len(files)
    for path in files:
        relative = path.relative_to(payload).as_posix()
        assert relative.split('/')[0] in ('server', 'scripts', 'vlc')
        assert not re.search(r'control-token|library\.json|runtime\.json|\.pdb$', relative)
        assert path.suffix not in ('.py', '.pyc'), 'Development Python worker shipped in installer'
    check = run_script(payload / 'scripts/check-prerequisites.ps1', '-Json')
    assert json.loads(check.stdout)['Ready']
    assert 'Python' not in json.loads(check.stdout)['Dependencies']
    missing = run_script(payload / 'scripts/check-prerequisites.ps1', '-VlcDirectory', work / 'missing-vlc', '-Json', success=False)
    assert missing.returncode != 0 and not json.loads(missing.stdout)['Ready']
    installed = work / 'Installed Caf\u00e9 & app'
    extension = work / 'VLC extensions'
    install_arguments = ('-Destination', installed, '-ExtensionDirectory', extension, '-NoLaunch')
    run_script(payload / 'scripts/install-vlc-plugin.ps1', *install_arguments)
    config_path = installed / 'build/library.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    assert not config['Enabled'] and config['Folders'] == []
    token_path = installed / 'build/library.json.control-token'
    token = token_path.read_bytes()
    assert re.fullmatch(rb'[A-F0-9]{64}', token)
    bootstrap = (extension / 'modules/library_share_config.lua').read_text()
    assert 'manage_lifetime = true' in bootstrap and token.decode() in bootstrap
    media = work / 'Original media'
    media.mkdir()
    original = media / 'Keep.mp4'
    original.write_bytes(b'original media must remain untouched')
    config.update(Enabled=True, Folders=[str(media)], Name='Upgrade test')
    config_path.write_text(json.dumps(config), encoding='utf-8')
    playback = installed / 'build/library.json.playback.json'
    playback.write_text('{"Font":"Test font"}', encoding='utf-8')
    prepared = installed / 'build/Prepared Media/Keep.mkv'
    prepared.parent.mkdir()
    prepared.write_bytes(b'keep prepared output too')
    extra = installed / 'keep my notes.txt'
    extra.write_text('Unmanaged user file')
    extra_script = installed / 'scripts/keep my script.ps1'
    extra_script.write_text('# Unmanaged file in a program folder')
    unrelated_extension = extension / 'another_extension.lua'
    unrelated_extension.write_text('-- unrelated extension')
    before = {p: p.read_bytes() for p in (config_path, token_path, playback, prepared, original, extra, extra_script, unrelated_extension)}
    run_script(payload / 'scripts/install-vlc-plugin.ps1', *install_arguments)
    assert all(p.read_bytes() == data for p, data in before.items()), 'Upgrade changed saved settings or media'
    manifest_path = installed / 'installed-files.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    assert not manifest['Registered']
    invalid = dict(manifest, Files=manifest['Files'] + [r'..\Original media\Keep.mp4'])
    manifest_path.write_text(json.dumps(invalid), encoding='utf-8')
    refused = run_script(installed / 'scripts/uninstall.ps1', '-Quiet', success=False)
    assert refused.returncode != 0 and (installed / 'server/LibraryShare.Server.exe').exists()
    assert all(p.read_bytes() == data for p, data in before.items()), 'Rejected uninstall changed data'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    run_script(installed / 'scripts/uninstall.ps1', '-Quiet')
    assert not (installed / 'server/LibraryShare.Server.exe').exists()
    assert not (extension / 'library_share.lua').exists()
    assert not (extension / 'modules/library_share_config.lua').exists()
    assert not manifest_path.exists()
    assert all(p.read_bytes() == data for p, data in before.items()), 'Uninstall changed saved settings or media'
    print('PASS: actual EXE extraction; prerequisite checks; fresh install OFF/empty with new token and working bootstrap; upgrade preservation; bounded uninstall preserves data and unrelated files')
    print('Artifacts: ' + str(work))


if __name__ == '__main__': main()
