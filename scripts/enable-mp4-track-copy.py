"""Enable one MP4 track in a separate workspace copy; never edit the input.

Some MP4s mark alternate audio tracks disabled. This test utility changes only
the tkhd enabled bit in a scratch copy, allowing VLC to select that audio track.
"""
import argparse
import pathlib
import shutil
import struct

ROOT = pathlib.Path(__file__).resolve().parents[1]


def boxes(stream, start, end):
    position = start
    count = 0
    while position + 8 <= end:
        count += 1
        if count > 100000:
            raise ValueError("Too many MP4 boxes")
        stream.seek(position)
        size, kind = struct.unpack(">I4s", stream.read(8))
        header = 8
        if size == 1:
            extended = stream.read(8)
            if len(extended) != 8:
                raise ValueError("Truncated extended box")
            size = struct.unpack(">Q", extended)[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or size > end - position:
            raise ValueError("Invalid MP4 box boundary")
        yield kind, position + header, position + size
        position += size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--track-id", type=int, required=True)
    options = parser.parse_args()
    source = options.input.resolve(strict=True)
    output = options.output.resolve()
    if not output.is_relative_to(ROOT / "build") or output == source:
        parser.error("Output must be a different file within this project's build directory")
    original = source.stat()
    matches = []
    with source.open("rb") as stream:
        for kind, begin, end in boxes(stream, 0, original.st_size):
            if kind != b"moov":
                continue
            for child, track_begin, track_end in boxes(stream, begin, end):
                if child != b"trak":
                    continue
                for leaf, payload, leaf_end in boxes(stream, track_begin, track_end):
                    if leaf != b"tkhd":
                        continue
                    stream.seek(payload)
                    data = stream.read(min(leaf_end - payload, 32))
                    if len(data) < 24 or data[0] not in (0, 1):
                        raise ValueError("Unsupported or truncated track header")
                    offset = 12 if data[0] == 0 else 20
                    track_id = struct.unpack_from(">I", data, offset)[0]
                    if track_id == options.track_id:
                        flags = int.from_bytes(data[1:4], "big")
                        matches.append((payload + 1, flags))
    if len(matches) != 1:
        raise SystemExit("Expected exactly one matching MP4 track")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    offset, flags = matches[0]
    with output.open("r+b") as stream:
        stream.seek(offset)
        stream.write((flags | 1).to_bytes(3, "big"))
    after = source.stat()
    if (original.st_size, original.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SystemExit("Source changed externally during copy; review before continuing")
    print(f"Enabled track {options.track_id} in workspace copy only; source size and modification time unchanged.")


if __name__ == "__main__":
    main()
