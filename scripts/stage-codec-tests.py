"""Copy selected codec fixtures into the project share; never write to J:."""
import collections
import hashlib
import json
import pathlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = pathlib.Path(r"J:\0001 media\TV Shows")
LABELS = {
    "HEVC 10-bit": "HEVC 10-bit",
    "HEVC 8-bit": "HEVC 8-bit",
    "AC-3 surround": "AC3 surround",
    "E-AC-3 surround": "EAC3 surround and ASS subtitles",
    "Mono audio": "Mono audio",
    "Bitmap subtitles": "Bitmap subtitles",
    "Multiple audio tracks": "Multiple audio tracks",
}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    source_root = SOURCE.resolve(strict=True)
    report = pathlib.Path((ROOT / "build/media-inventory/latest.txt").read_text()).resolve(strict=True)
    if not report.is_relative_to(ROOT / "build/media-inventory"):
        raise SystemExit("Inventory pointer is outside the project report directory.")
    candidates = json.loads((report / "next-tests.json").read_text(encoding="utf-8"))
    by_path = collections.OrderedDict()
    for candidate in candidates:
        by_path.setdefault(candidate["relative_path"], []).append(candidate["case"])
    destination = ROOT / "build/TV Test/Codec Samples"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, (relative, cases) in enumerate(by_path.items(), 1):
        original = (source_root / relative).resolve(strict=True)
        if not original.is_relative_to(source_root) or not original.is_file():
            raise SystemExit("A candidate is outside the allowed source library or is not a file.")
        label = LABELS[cases[0]]
        output = destination / (f"{index:02d} - {label}" + original.suffix.lower())
        temporary = output.with_suffix(output.suffix + ".copying")
        before = original.stat()
        digest = hashlib.sha256()
        copied = 0
        # The original is opened rb only. Partial files have an unsupported
        # extension and cannot be indexed as playable media while being copied.
        with original.open("rb") as source, temporary.open("wb") as target:
            while block := source.read(4 * 1024 * 1024):
                target.write(block)
                digest.update(block)
                copied += len(block)
        after = original.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or copied != before.st_size:
            raise SystemExit(f"Source changed during copy; the partial project copy was not published: {relative}")
        if file_hash(temporary) != digest.hexdigest():
            raise SystemExit("Project copy failed SHA-256 verification; partial copy not published.")
        temporary.replace(output)
        manifest.append({"cases": cases, "source_relative_path": relative,
                         "project_copy": str(output.relative_to(ROOT)), "bytes": copied,
                         "sha256": digest.hexdigest(), "source_size_and_mtime_unchanged": True})
        print(f"Ready {index}/{len(by_path)}: {output.name} ({copied / 1024**2:.1f} MiB)", flush=True)
    (destination / "copy-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    token = (ROOT / "build/library.json.control-token").read_text().strip()
    query = urllib.parse.urlencode({"token": token, "action": "rescan"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:57642/local?" + query, timeout=15) as response:
            state = ET.fromstring(response.read())
    except OSError:
        raise SystemExit("Copies are ready, but the sharing helper could not be refreshed. Start it and rescan.") from None
    if state.tag == "error":
        raise SystemExit(state.text)
    print(state.findtext("summary"), flush=True)
    print(f"Staged {len(manifest)} byte-verified copies covering {len(candidates)} test cases.", flush=True)


if __name__ == "__main__":
    main()
