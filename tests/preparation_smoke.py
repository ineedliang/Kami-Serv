"""Actual VLC preparation through the authenticated helper API.

Uses existing workspace TV fixtures read-only. Publishes only into an isolated
test config's build directory, never into the running TV server or source share.
ffprobe independently validates outputs; it does not encode them.
"""
import json
import os
import pathlib
import shutil
import subprocess
import time

from integration import Integration, ROOT

PROBE = pathlib.Path(r"G:\.0000PROJECTS\_kit\shared\ffmpeg\2026-08-17-full_build-gyan\ffprobe.exe")


def wait_ready(test):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        message = test.control().findtext("summary")
        if "Preparation failed:" in message:
            raise AssertionError(message)
        if "Ready in Prepared for TV:" in message:
            return
        time.sleep(.2)
    raise AssertionError("Preparation did not complete")


def main():
    tracks = ROOT / "build/TV Test/Track Tests/Multi Audio - Original.mkv"
    subtitles = ROOT / "build/TV Test/Codec Samples/06 - Bitmap subtitles.mp4"
    assert tracks.exists() and subtitles.exists(), "Workspace TV fixtures are needed for this check"
    before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (tracks, subtitles)]
    # Python runs this development test, but is deliberately absent from the
    # server/worker environment, exactly as on a tester's PC without Python.
    previous_path = os.environ.get('PATH', '')
    os.environ['PATH'] = os.pathsep.join((str(pathlib.Path(os.environ['WINDIR']) / 'System32'),
        os.environ['WINDIR'], str(pathlib.Path(os.environ['ProgramFiles']) / 'dotnet')))
    assert shutil.which('python') is None
    Integration.setUpClass()
    test = Integration()
    try:
        for source in (tracks, subtitles):
            test.control("add", folder=str(source.parent))
        test.control("enable")
        preferences = dict(audio="dolby", position="bottom", offset="0", font="Arial", size="26", bold="false", color="FFFFFF", outline="2")
        for source, burn, audio in ((tracks, False, "dolby"), (tracks, False, "aac"), (subtitles, True, "dolby")):
            response = test.control("settings", **dict(preferences, audio=audio))
            assert response.tag != "error", response.text
            entries = test.control()
            pairs = list(zip(entries.findall("./videos/videoId"), entries.findall("./videos/videoTitle")))
            identifier = next(i.text for i, title in pairs if title.text == source.name)
            result = test.control("prepare", id=identifier, burn=str(burn).lower(), subtitle="0", full="false")
            assert result.tag != "error", result.text
            wait_ready(test)
        outputs = sorted((test.work / "Prepared Media").glob("*.mkv"))
        assert len(outputs) == 3, outputs
        results = [json.loads(path.read_text()) for path in (test.work / 'preparation').glob('*/output.mkv.result.json')]
        assert len(results) == 3 and all(result['Engine'] == 'LibVLC via .NET' for result in results)
        assert {result['SelectedAudio']['Codec'] for result in results if not result['BurnSubtitles']} == {'a52', 'mp4a'}
        validations = []
        for output in outputs:
            result = subprocess.run([str(PROBE), "-v", "error", "-show_entries", "stream=codec_name,codec_type,channels:format=duration",
                "-of", "json", str(output)], check=True, capture_output=True, text=True)
            metadata = json.loads(result.stdout)
            audio = [s for s in metadata["streams"] if s["codec_type"] == "audio"]
            assert len(audio) == 1 and audio[0]["channels"] == 2, metadata
            expected = "mp3" if "Captions" in output.name else "ac3" if "dolby" in output.name else "aac"
            assert audio[0]["codec_name"] == expected, metadata
            assert 119 < float(metadata["format"]["duration"]) < 122, metadata
            validations.append(dict(file=str(output), metadata=metadata))
        (test.work / "preparation-validation.json").write_text(json.dumps(validations, indent=2))
        assert before == [(p.stat().st_size, p.stat().st_mtime_ns) for p in (tracks, subtitles)]
        print("PASS: .NET/LibVLC preparation with Python absent from PATH; selected Dolby/AAC independently; bitmap burn-in; three valid stereo MKVs")
        print("Artifacts: " + str(test.work))
    finally:
        Integration.tearDownClass()
        os.environ['PATH'] = previous_path


if __name__ == "__main__":
    main()
