"""Publish only independently validated track/subtitle compatibility fixtures."""
import json
import pathlib
import shutil
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = pathlib.Path(r"G:\.0000PROJECTS\_kit\shared\ffmpeg\2026-08-17-full_build-gyan\ffprobe.exe")


def main():
    work = ROOT / "build/track-compatibility"
    destination = ROOT / "build/TV Test/Track Tests"
    fixtures = [
        ("King of the Hill - Captions Burned In - 2 min.mkv", 1, "h264", "mp3"),
        ("Multi Audio - Original.mkv", 2, "hevc", None),
        ("Multi Audio - Selected AC3 - 2 min.mkv", 1, "hevc", "ac3"),
        ("Multi Audio - Selected AAC - 2 min.mkv", 1, "hevc", "aac"),
    ]
    validated = []
    for filename, audio_count, video_codec, audio_codec in fixtures:
        source = work / filename
        process = subprocess.run([str(PROBE), "-v", "error", "-show_entries",
            "stream=codec_type,codec_name:format=duration", "-of", "json", str(source)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
        metadata = json.loads(process.stdout)
        audio = [s for s in metadata["streams"] if s.get("codec_type") == "audio"]
        video = [s for s in metadata["streams"] if s.get("codec_type") == "video"]
        if len(audio) != audio_count or len(video) != 1 or video[0]["codec_name"] != video_codec:
            raise SystemExit("Unexpected tracks; fixture not published: " + filename)
        if audio_codec and audio[0]["codec_name"] != audio_codec:
            raise SystemExit("Incorrect selected audio; fixture not published: " + filename)
        validated.append((source, metadata))
    destination.mkdir(parents=True, exist_ok=True)
    for source, _ in validated:
        shutil.copyfile(source, destination / source.name)
        print("Published: " + source.name)
    (destination / "validation.json").write_text(json.dumps(
        [{"file": source.name, "metadata": metadata} for source, metadata in validated], indent=2))
    token = (ROOT / "build/library.json.control-token").read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        query = urllib.parse.urlencode({"token": token, "action": "rescan"})
        with opener.open("http://127.0.0.1:57642/local?" + query, timeout=15) as response:
            status = ET.fromstring(response.read())
    except OSError:
        raise SystemExit("Fixtures are copied; start the helper and rescan to publish them.") from None
    if status.tag == "error":
        raise SystemExit(status.text)
    print(status.findtext("summary"))


if __name__ == "__main__":
    main()
