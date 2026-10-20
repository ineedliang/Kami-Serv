"""SRT discovery, safe delivery, selection, copy and actual VLC burn-in.

Only generated fixtures under build/ are used. ffmpeg/ffprobe from the existing
developer kit generate/check fixtures; the application itself uses .NET/LibVLC.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from integration import Integration, ROOT, DIDL
from libvlc_smoke import lua_api

KIT = pathlib.Path(r'G:\.0000PROJECTS\_kit\shared\ffmpeg\2026-08-17-full_build-gyan')
FFMPEG = KIT / 'ffmpeg.exe'
PROBE = KIT / 'ffprobe.exe'


def main():
    previous_path = os.environ['PATH']
    os.environ['PATH'] = os.pathsep.join((str(pathlib.Path(os.environ['WINDIR']) / 'System32'),
        os.environ['WINDIR'], str(pathlib.Path(os.environ['ProgramFiles']) / 'dotnet')))
    assert shutil.which('python') is None
    Integration.setUpClass()
    test = Integration()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def fetch(url, expected=200, **kwargs):
        try: response = opener.open(urllib.request.Request(url, **kwargs), timeout=5)
        except urllib.error.HTTPError as error: response = error
        with response:
            assert response.status == expected, (url, response.status, expected)
            return response.headers, response.read()
    def media_id(path): return hashlib.sha256(str(path.resolve()).upper().encode()).hexdigest()[:32].upper()
    def choices(path): return test.control('subtitles', id=media_id(path))
    def srt_url(path, name): return f'{test.base}/media/{media_id(path)}/' + urllib.parse.quote(name)
    def wait_ready():
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            message = test.control().findtext('summary')
            assert 'Preparation failed:' not in message, message
            if 'Ready in Prepared for TV:' in message: return
            time.sleep(.1)
        raise AssertionError('SRT preparation timed out')
    try:
        captions = '1\n00:00:01,000 --> 00:00:04,500\nKAMI-SERV SRT TEST\n\n'
        sidecar = test.media / 'A & B.srt'
        sidecar.write_text(captions, encoding='utf-8')
        english = test.media / 'A & B.eng.srt'
        english.write_text(captions.replace('KAMI', 'ENGLISH KAMI'), encoding='utf-8')
        spanish = test.media / 'A & B.spa.srt'
        spanish.write_text(captions.replace('KAMI', 'SPANISH KAMI'), encoding='utf-8')
        (test.media / 'Unmatched.srt').write_text(captions)
        (test.media / 'A & B.Notes.txt').write_text('Do not serve')
        hidden = test.media / 'A & B.hidden.srt'
        hidden.write_text(captions)
        import ctypes
        assert ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 2)
        empty = test.media / 'A & B.empty.srt'; empty.touch()
        oversized = test.media / 'A & B.large.srt'
        with oversized.open('wb') as stream: stream.truncate(16 * 1024 * 1024 + 1)
        (test.media / 'A & B.Part2.mp4').write_bytes(b'Other video')
        twin = test.media / 'A & B.mkv'
        twin.write_bytes(b'Same base name, different container')
        (test.media / 'A & B.Part2.eng.srt').write_text(captions)
        video = test.media / 'A & B.mp4'
        root_id = test.enable()
        items, _ = test.browse(root_id)
        item = next(item for item in items if item.attrib['id'] == media_id(video))
        assert not any(item.find('{http://purl.org/dc/elements/1.1/}title').text.endswith('.srt') for item in items)
        resources = item.findall(f'{{{DIDL}}}res')
        assert len(resources) == 4 and resources[0].attrib['protocolInfo'].startswith('http-get:*:video/')
        assert {r.attrib.get('language') for r in resources[1:]} == {'und','eng','spa'}
        assert item.find('{http://www.sec.co.kr/}CaptionInfoEx').text == srt_url(video, sidecar.name)
        assert resources[0].attrib['{http://www.pv.com/pvns/}subtitleFileUri'] == srt_url(video, sidecar.name)
        result = choices(video)
        names = [e.text for e in result.findall('./sidecars/sidecarName')]
        assert names == [sidecar.name, english.name, spanish.name], names
        assert [e.text for e in choices(twin).findall('./sidecars/sidecarName')] == names
        headers, content = fetch(resources[0].text, expected=206, headers={'Range':'bytes=0-15'})
        assert headers['CaptionInfo.sec'] == srt_url(video, sidecar.name)
        for resource in resources[1:]:
            headers, content = fetch(resource.text)
            assert headers['Content-Type'] == 'text/srt' and b'-->' in content
        headers, content = fetch(srt_url(video, sidecar.name), method='HEAD')
        assert not content and int(headers['Content-Length']) == len(sidecar.read_bytes())
        _, content = fetch(srt_url(video, sidecar.name), expected=206, headers={'Range':'bytes=0-7'})
        assert content == sidecar.read_bytes()[:8]
        for name in ['Unmatched.srt', hidden.name, empty.name, oversized.name, 'A & B.Part2.eng.srt', '../Unmatched.srt']:
            fetch(srt_url(video, name), expected=404)
        assert test.control('subtitles', id=root_id).tag == 'error'
        part2 = choices(test.media / 'A & B.Part2.mp4')
        foreign_id = part2.findtext('./sidecars/sidecarId')
        assert test.control('prepare', id=media_id(video), burn='true', subtitle='0', full='false', sidecar=foreign_id).tag == 'error'
        test.control('disable'); fetch(srt_url(video, sidecar.name), expected=503); test.control('enable')
        english.unlink(); test.control('rescan')
        fetch(srt_url(video, english.name), expected=404)
        assert len(choices(video).findall('./sidecars/sidecarId')) == 2
        test.control('add', folder=str(test.media), mediaType='audio')
        fetch(srt_url(video, sidecar.name), expected=404)
        test.control('add', folder=str(test.media), mediaType='video')
        test.control('remove', folder=str(test.media))
        fetch(srt_url(video, sidecar.name), expected=404)
        test.control('add', folder=str(test.media), mediaType='video')
        print('PASS: SRT pairing, language metadata, HTTP/HEAD/ranges, no standalone captions, hidden/oversize/unmatched protection, rescan/filter/disable/remove revocation')

        real = test.media / "Caf\u00e9 & O'Brien.mp4"
        subprocess.run([str(FFMPEG),'-v','error','-f','lavfi','-i','color=c=black:s=640x360:r=25:d=6',
            '-f','lavfi','-i','sine=frequency=440:duration=6','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-y',str(real)],check=True)
        real_srt = real.with_suffix('.eng.srt')
        real_srt.write_text(captions,encoding='utf-8')
        before = {p: (p.stat().st_size,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in (real,real_srt)}
        test.control('rescan')
        srt_id = choices(real).findtext('./sidecars/sidecarId')
        test.control('settings',audio='default',position='bottom',offset='0',font='Arial',size='32',bold='true',color='FFFFFF',outline='2')
        for burn in (False,True):
            response = test.control('prepare',id=media_id(real),burn=str(burn).lower(),subtitle='0',full='true',sidecar=srt_id)
            assert response.tag != 'error', response.text
            wait_ready()
        outputs = list((test.work/'Prepared Media').glob('*.mkv'))
        assert len(outputs)==2
        burned = next(p for p in outputs if 'Captions' in p.name)
        copied = next(p for p in outputs if 'Audio' in p.name)
        assert copied.with_suffix('.srt').read_bytes()==real_srt.read_bytes()
        assert not burned.with_suffix('.srt').exists()
        assert len(choices(copied).findall('./sidecars/sidecarId'))==1
        def frame_pixels(path):
            return subprocess.check_output([str(FFMPEG),'-v','error','-ss','2','-i',str(path),'-frames:v','1','-vf','format=gray','-f','rawvideo','-'])
        raw_pixels = frame_pixels(real)
        burned_pixels = frame_pixels(burned)
        # Solid-black source: pixels becoming bright in the lower third prove the
        # external SRT was actually rendered, not merely accepted as an option.
        assert sum(value>160 for value in raw_pixels)==0
        assert sum(value>160 for value in burned_pixels[640*240:])>300, 'SRT captions were not burned into the lower picture'
        subprocess.run([str(FFMPEG),'-v','error','-ss','2','-i',str(burned),'-frames:v','1','-y',str(test.work/'srt-burn-in.png')],check=True)
        for output in outputs:
            metadata=json.loads(subprocess.check_output([str(PROBE),'-v','error','-show_streams','-of','json',str(output)]))
            assert {s['codec_type'] for s in metadata['streams']}=={'video','audio'}
        assert all((p.stat().st_size,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest())==state for p,state in before.items())
        test.control('remove',folder=str(test.work/'Prepared Media'))
        lua_api(pathlib.Path(os.environ.get('VLC_DIR',r'C:\Program Files\VideoLAN\VLC')),test,srt_tests=True)
        print('PASS: real .NET/LibVLC selected-SRT copy and visible burn-in; Unicode paths; source hashes/times unchanged; Python absent from app PATH')
        print('Artifacts: '+str(test.work))
    finally:
        Integration.tearDownClass()
        os.environ['PATH']=previous_path


if __name__=='__main__': main()
