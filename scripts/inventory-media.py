"""Read-only, stratified codec inventory. Reports are written under this project.

ffprobe is only invoked as a reader. No source files are repaired, renamed,
replaced, moved, or deleted. The source tree is never added to the shared library.
"""
import argparse
import collections
import concurrent.futures
import csv
import datetime
import json
import os
import pathlib
import re
import stat
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTENSIONS = {".mp4", ".mkv", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg", ".wmv", ".webm", ".vob", ".flv", ".ogm"}
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
MARKERS = re.compile(r"(?i)(x26[45]|h[._ -]?26[45]|hevc|av1|xvid|divx|10bit|10.bit|2160p|1080p|720p|hdr|dolby|dts|eac3|ddp|ac3|aac)")


def enumerate_media(source):
    files, errors = [], []
    def on_error(error):
        errors.append({"path": error.filename, "error": str(error)})
    for folder, directories, names in os.walk(source, followlinks=False, onerror=on_error):
        safe_directories = []
        for name in sorted(directories, key=str.casefold):
            path = pathlib.Path(folder) / name
            try:
                if not path.lstat().st_file_attributes & REPARSE:
                    safe_directories.append(name)
            except OSError as error:
                on_error(error)
        directories[:] = safe_directories
        for name in sorted(names, key=str.casefold):
            path = pathlib.Path(folder) / name
            if path.suffix.lower() not in EXTENSIONS:
                continue
            try:
                info = path.lstat()
                if info.st_file_attributes & REPARSE:
                    continue
                files.append({"relative_path": str(path.relative_to(source)), "size": info.st_size,
                              "mtime_ns": info.st_mtime_ns, "extension": path.suffix.lower()})
            except OSError as error:
                on_error(error)
    return files, errors


def choose_samples(files, limit):
    # Group by series, parent folder, extension, and filename format clues. This
    # avoids spending the whole budget on consecutive episodes of one encoding.
    groups = collections.defaultdict(list)
    for file in files:
        relative = pathlib.Path(file["relative_path"])
        series = relative.parts[0] if len(relative.parts) > 1 else "(root)"
        markers = tuple(sorted({m.group().lower().replace(".", "").replace("-", "")
                                for m in MARKERS.finditer(relative.name)}))
        groups[(series, str(relative.parent), file["extension"], markers)].append(file)
    by_series = collections.defaultdict(list)
    for (series, parent, extension, markers), members in sorted(groups.items()):
        # A middle episode reduces the chance of choosing a tiny intro/sample.
        eligible = [member for member in members if member["size"] >= 5_000_000] or members
        by_series[series].append(eligible[len(eligible) // 2])
    selected = []
    for turn in range(max((len(values) for values in by_series.values()), default=0)):
        for series in sorted(by_series, key=str.casefold):
            values = by_series[series]
            if turn < len(values):
                selected.append(values[turn])
                if len(selected) >= limit:
                    return selected, len(groups)
    return selected, len(groups)


def probe_one(source, probe, record):
    path = source / record["relative_path"]
    command = [str(probe), "-v", "error", "-protocol_whitelist", "file", "-probesize", "5000000",
               "-analyzeduration", "5000000", "-show_entries",
               "format=format_name,duration,size,bit_rate:"
               "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,bits_per_raw_sample,"
               "avg_frame_rate,field_order,color_space,color_transfer,color_primaries,sample_rate,channels,channel_layout:"
               "stream_tags=language:stream_side_data=side_data_type,dv_profile,dv_level,dv_bl_signal_compatibility_id",
               "-of", "json", "-i", str(path)]
    result = dict(record)
    began = time.monotonic()
    try:
        process = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=25,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result["probe_seconds"] = round(time.monotonic() - began, 3)
        if process.returncode != 0:
            result["error"] = process.stderr[-1200:]
        else:
            result["metadata"] = json.loads(process.stdout)
            if process.stderr.strip():
                result["warnings"] = process.stderr[-1200:]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        result["error"] = str(error)
    try:
        after = path.stat()
        result["source_size_and_mtime_unchanged"] = after.st_size == record["size"] and after.st_mtime_ns == record["mtime_ns"]
    except OSError as error:
        result["source_check_error"] = str(error)
    return result


def signature(result):
    streams = result.get("metadata", {}).get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = sorted({f"{s.get('codec_name', '?')}/{s.get('channels', '?')}ch/{s.get('sample_rate', '?')}Hz"
                    for s in streams if s.get("codec_type") == "audio"})
    subtitles = sorted({s.get("codec_name", "?") for s in streams if s.get("codec_type") == "subtitle"})
    # Resolution, profile, and HDR signaling can change device compatibility.
    return (video.get("codec_name", "?"), video.get("profile", "?"), video.get("pix_fmt", "?"),
            f"{video.get('width', '?')}x{video.get('height', '?')}", video.get("color_transfer", "unspecified"),
            ", ".join(audio) or "none", ", ".join(subtitles) or "none")


def summarize(source, files, results, skipped, group_count):
    successes = [r for r in results if "metadata" in r]
    video_counts = collections.Counter()
    audio_counts = collections.Counter()
    subtitle_counts = collections.Counter()
    combinations = collections.defaultdict(list)
    for result in successes:
        for stream in result["metadata"].get("streams", []):
            kind = stream.get("codec_type")
            if kind == "video":
                video_counts[(stream.get("codec_name", "?"), stream.get("profile", "?"), stream.get("pix_fmt", "?"))] += 1
            elif kind == "audio":
                audio_counts[(stream.get("codec_name", "?"), stream.get("channels", "?"))] += 1
            elif kind == "subtitle":
                subtitle_counts[stream.get("codec_name", "?")] += 1
        combinations[signature(result)].append(result)
    changed = [r["relative_path"] for r in results if r.get("source_size_and_mtime_unchanged") is not True]
    report = {"source": str(source), "files_enumerated": len(files),
              "bytes_enumerated": sum(f["size"] for f in files), "candidate_groups": group_count,
              "files_probed": len(results), "successful_probes": len(successes),
              "probe_errors": len(results) - len(successes), "enumeration_errors": len(skipped),
              "distinct_sampled_combinations": len(combinations),
              "video_stream_counts": [{"codec": k[0], "profile": k[1], "pixel_format": k[2], "streams": n}
                                      for k, n in video_counts.most_common()],
              "audio_stream_counts": [{"codec": k[0], "channels": k[1], "streams": n}
                                      for k, n in audio_counts.most_common()],
              "subtitle_stream_counts": dict(subtitle_counts),
              "files_with_size_or_modification_time_change": changed,
              "scope": "Stratified sample, not an exhaustive codec inventory. Counts describe probed streams only."}
    lines = ["# Read-only media inventory", "", f"Source: `{source}`", "",
             f"Enumerated **{len(files):,} media files** ({report['bytes_enumerated'] / 1024**4:.2f} TiB).",
             f"Probed **{len(results)} selected files** across series, folders, extensions, and filename encoding clues.",
             f"Successful probes: {len(successes)}; probe errors: {report['probe_errors']}; enumeration errors: {len(skipped)}.",
             "", "The source library was only read. No source paths were shared with the TV or written to.",
             "Source size and modification-time checks: " + ("all probed files unchanged." if not changed else f"{len(changed)} changes detected; inspect JSON."),
             "These checks are not whole-file content hashes. Normal filesystem access-time handling is controlled by Windows.",
             "", "Counts below describe the sample, not every file in the library.", "", "## Video streams", "",
             "| Codec | Profile | Pixel format | Streams |", "| --- | --- | --- | --- |"]
    for (codec, profile, pixels), count in video_counts.most_common():
        lines.append(f"| {codec} | {profile} | {pixels} | {count} |")
    lines += ["", "## Audio streams", "", "| Codec | Channels | Streams |", "| --- | --- | --- |"]
    for (codec, channels), count in audio_counts.most_common():
        lines.append(f"| {codec} | {channels} | {count} |")
    lines += ["", "## Representative test candidates", "",
              "These are inspection candidates, not verified TV compatibility results. Source files remain in place.", "",
              "| Video | Pixels / HDR transfer | Audio | Subtitles | Example source path |", "| --- | --- | --- | --- | --- |"]
    representatives = []
    for key, members in sorted(combinations.items()):
        example = min(members, key=lambda r: r["size"])
        representatives.append({"signature": list(key), "relative_path": example["relative_path"], "size": example["size"]})
        safe_path = example["relative_path"].replace("|", "\\|").replace("`", "'")
        lines.append(f"| {key[0]} ({key[1]}) | {key[2]}, {key[3]}, {key[4]} | {key[5]} | {key[6]} | `{safe_path}` |")
    lines += ["", "## Next tests", "", "Copy or extract selected samples into the project's test area before playback tests.",
              "Keep direct playback first; remux or transcode only when device tests show a need.",
              "VLC remains the planned playback/remux/transcode engine. ffprobe was used only to inspect metadata.", ""]
    return report, representatives, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("--max-files", type=int, default=160)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--probe", type=pathlib.Path, default=pathlib.Path(r"G:\.0000PROJECTS\_kit\shared\ffmpeg\2026-08-17-full_build-gyan\ffprobe.exe"))
    options = parser.parse_args()
    source = options.source.resolve(strict=True)
    if not source.is_dir() or source.lstat().st_file_attributes & REPARSE:
        parser.error("Choose a real source directory, not a junction/symlink")
    if options.max_files < 1 or not 1 <= options.workers <= 4:
        parser.error("Choose a positive sample size and 1–4 workers")
    if not options.probe.is_file():
        parser.error("ffprobe executable not found")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = ROOT / "build/media-inventory" / stamp
    destination.mkdir(parents=True)
    files, skipped = enumerate_media(source)
    selected, group_count = choose_samples(files, options.max_files)
    (destination / "source-manifest.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
    (destination / "enumeration-errors.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    print(f"Enumerated {len(files):,} media files; probing {len(selected)} selected files from {group_count} groups.", flush=True)
    results = []
    with (destination / "probes.jsonl").open("w", encoding="utf-8") as output:
        with concurrent.futures.ThreadPoolExecutor(max_workers=options.workers) as executor:
            futures = [executor.submit(probe_one, source, options.probe, record) for record in selected]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                output.write(json.dumps(result, ensure_ascii=False) + "\n")
                output.flush()
                if len(results) % 20 == 0 or len(results) == len(selected):
                    print(f"Probed {len(results)}/{len(selected)}; errors: {sum('error' in r for r in results)}", flush=True)
    summary, representatives, markdown = summarize(source, files, results, skipped, group_count)
    (destination / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (destination / "candidates.json").write_text(json.dumps(representatives, indent=2), encoding="utf-8")
    (destination / "report.md").write_text(markdown, encoding="utf-8")
    with (destination / "candidates.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["video_codec", "profile", "pixel_format", "resolution", "transfer", "audio", "subtitles", "relative_path", "bytes"])
        for candidate in representatives:
            writer.writerow(candidate["signature"] + [candidate["relative_path"], candidate["size"]])
    # A pointer inside the project makes it easy to resume without touching the library.
    (ROOT / "build/media-inventory/latest.txt").write_text(str(destination), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print("Report: " + str(destination / "report.md"), flush=True)


if __name__ == "__main__":
    main()
