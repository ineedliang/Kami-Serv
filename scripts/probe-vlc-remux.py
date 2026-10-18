"""Exercise installed VLC muxers, track selection, and optional subtitle burn-in.

Defaults to stream copy. --burn-subtitles explicitly enables video transcoding.
"""
import argparse
import ctypes
import json
import os
import pathlib
import time


class Audio(ctypes.Structure):
    _fields_ = [("channels", ctypes.c_uint), ("rate", ctypes.c_uint)]


class Track(ctypes.Structure):
    # Public LibVLC 3 media-track ABI; the codec-specific union is one pointer.
    _fields_ = [("codec", ctypes.c_uint32), ("original", ctypes.c_uint32),
                ("id", ctypes.c_int), ("type", ctypes.c_int),
                ("profile", ctypes.c_int), ("level", ctypes.c_int),
                ("details", ctypes.c_void_p), ("bitrate", ctypes.c_uint),
                ("language", ctypes.c_char_p), ("description", ctypes.c_char_p)]


def inspect_tracks(vlc, media):
    parse = vlc.libvlc_media_parse_with_options
    parse.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    parse.restype = ctypes.c_int
    status = vlc.libvlc_media_get_parsed_status
    status.argtypes = [ctypes.c_void_p]
    status.restype = ctypes.c_int
    if parse(media, 0, 10000) != 0:
        raise RuntimeError("VLC could not inspect this file")
    deadline = time.monotonic() + 12
    while status(media) == 0 and time.monotonic() < deadline:
        time.sleep(.02)
    if status(media) != 4:
        raise RuntimeError("VLC media inspection failed or timed out")
    track_pointer = ctypes.POINTER(Track)
    array = ctypes.POINTER(track_pointer)()
    get = vlc.libvlc_media_tracks_get
    get.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(track_pointer))]
    get.restype = ctypes.c_uint
    free = vlc.libvlc_media_tracks_release
    free.argtypes = [ctypes.POINTER(track_pointer), ctypes.c_uint]
    count = get(media, ctypes.byref(array))
    tracks = []
    try:
        indices = {0: 0, 1: 0, 2: 0}
        for i in range(count):
            track = array[i].contents
            index = indices.get(track.type, 0)
            indices[track.type] = index + 1
            item = {"type": track.type, "index": index, "id": track.id,
                    "codec": track.codec.to_bytes(4, "little").decode("ascii", "replace").strip(),
                    "language": (track.language or b"").decode("utf-8", "replace"),
                    "description": (track.description or b"").decode("utf-8", "replace")}
            if track.type == 0 and track.details:
                audio = ctypes.cast(track.details, ctypes.POINTER(Audio)).contents
                item.update(channels=audio.channels, rate=audio.rate)
            tracks.append(item)
    finally:
        free(array, count)
    return tracks


def preferred_audio(tracks, preference):
    # Language wins over codec: never pick foreign-language Dolby over English.
    english = [t for t in tracks if t["type"] == 0 and
               t["language"].lower() in ("en", "eng", "english")]
    codecs = {"dolby": ("a52", "eac3"), "aac": ("mp4a",)}.get(preference, ())
    return next((t for t in english if t["codec"] in codecs), None)


def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=root / "build/TV Test/Library Share - TV Test.mp4")
    parser.add_argument("--output", type=pathlib.Path, help="Output filename for one selected muxer")
    parser.add_argument("--mux", choices=["all", "mkv", "avformat-matroska", "mpeg-ts"], default="all")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--audio-track", type=int, help="Zero-based VLC audio track index")
    parser.add_argument("--audio-track-id", type=int, help="Explicit VLC stream ID, for tracks not selected by index")
    parser.add_argument("--sub-track", type=int, help="Zero-based VLC subtitle track index")
    parser.add_argument("--burn-subtitles", action="store_true", help="Encode H.264 video with the selected subtitles overlaid")
    parser.add_argument("--seconds", type=float, help="Process this many seconds from the beginning")
    parser.add_argument("--settings", type=pathlib.Path, help="Saved plugin TV preparation settings")
    parser.add_argument("--subtitle-position", choices=["file", "bottom", "top"])
    parser.add_argument("--subtitle-offset", type=int, help="Pixels upward from the file's subtitle position")
    options = parser.parse_args()
    settings = json.loads(options.settings.read_text()) if options.settings else {}
    position = options.subtitle_position or settings.get("SubtitlePosition", "file")
    offset = options.subtitle_offset if options.subtitle_offset is not None else settings.get("SubtitleOffset", 0)
    if position not in ("file", "bottom", "top") or not -1000 <= offset <= 1000:
        parser.error("Invalid subtitle position or offset")
    source = options.input.resolve(strict=True)
    if options.output and options.mux == "all":
        parser.error("Choose one --mux when using --output")
    if options.output and options.output.resolve() == source:
        parser.error("Output must not replace the input file")
    if options.burn_subtitles and (options.sub_track is None or options.mux == "all"):
        parser.error("Subtitle burn-in requires --sub-track and one --mux")
    if options.seconds is not None and options.seconds <= 0:
        parser.error("--seconds must be positive")
    target = root / "build/vlc-remux-check"
    target.mkdir(parents=True, exist_ok=True)
    vlc_dir = pathlib.Path(os.environ.get("VLC_DIR", r"C:\Program Files\VideoLAN\VLC"))
    with os.add_dll_directory(str(vlc_dir)):
        vlc = ctypes.CDLL(str(vlc_dir / "libvlc.dll"))
        def function(name, result, *args):
            callback = getattr(vlc, name)
            callback.restype = result
            callback.argtypes = args
            return callback
        pointer = ctypes.c_void_p
        new = function("libvlc_new", pointer, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p))
        release = function("libvlc_release", None, pointer)
        media_new = function("libvlc_media_new_path", pointer, pointer, ctypes.c_char_p)
        media_option = function("libvlc_media_add_option", None, pointer, ctypes.c_char_p)
        media_release = function("libvlc_media_release", None, pointer)
        player_new = function("libvlc_media_player_new_from_media", pointer, pointer)
        player_release = function("libvlc_media_player_release", None, pointer)
        play = function("libvlc_media_player_play", ctypes.c_int, pointer)
        stop = function("libvlc_media_player_stop", None, pointer)
        get_state = function("libvlc_media_player_get_state", ctypes.c_int, pointer)
        results = []
        for name, mux, extension in (("mkv", "mkv", ".mkv"),
                                     ("avformat-matroska", "avformat{mux=matroska}", ".mkv"),
                                     ("mpeg-ts", "ts", ".ts")):
            if options.mux not in ("all", name):
                continue
            output = options.output.resolve() if options.output else target / (name + extension)
            output.parent.mkdir(parents=True, exist_ok=True)
            log = output.with_suffix(output.suffix + ".vlc.log")
            args = ["--ignore-config", "--no-plugins-cache", "--no-media-library",
                    "--no-metadata-network-access", "--aout=dummy", "--vout=dummy",
                    "--file-logging", "--logfile=" + str(log), "--verbose=2"]
            if options.burn_subtitles:
                # VLC applies sub-margin then fits the region inside the video.
                # A large signed offset pins every cue to the corresponding edge,
                # including image subtitles whose authored positions change.
                margin = {"bottom": -32768, "top": 32768, "file": offset}[position]
                args += [f"--sub-margin={margin}", "--freetype-font=" + settings.get("Font", "Arial"),
                         "--freetype-fontsize=" + str(settings.get("FontSize", 26)),
                         "--freetype-bold" if settings.get("Bold", False) else "--no-freetype-bold",
                         "--freetype-color=" + str(int(settings.get("Color", "FFFFFF"), 16)),
                         "--freetype-outline-thickness=" + str(settings.get("Outline", 2))]
            argv = [argument.encode() for argument in args]
            instance = new(len(argv), (ctypes.c_char_p * len(argv))(*argv))
            if not instance:
                raise RuntimeError("Installed LibVLC did not initialize")
            media = media_new(instance, str(source).encode())
            player = None
            try:
                tracks = inspect_tracks(vlc, media)
                if options.burn_subtitles and not any(t["type"] == 2 and t["index"] == options.sub_track for t in tracks):
                    raise RuntimeError("The selected embedded subtitle track does not exist")
                selected = preferred_audio(tracks, settings.get("AudioPreference", "default"))
                audio_index = options.audio_track
                if audio_index is None and options.audio_track_id is None and selected:
                    audio_index = selected["index"]
                destination = output.as_posix().replace("\\", "\\\\").replace("'", "\\'")
                chain = "standard{access=file,mux=" + mux + ",dst='" + destination + "'}"
                if options.burn_subtitles:
                    chain = "transcode{vcodec=h264,venc=x264{preset=veryfast,crf=20},soverlay}:" + chain
                option = ":sout=#" + chain
                media_option(media, option.encode())
                media_option(media, b":no-sout-keep")
                media_option(media, b":no-sout-all")
                if audio_index is not None:
                    media_option(media, f":audio-track={audio_index}".encode())
                if options.audio_track_id is not None:
                    media_option(media, f":audio-track-id={options.audio_track_id}".encode())
                if options.sub_track is not None:
                    media_option(media, f":sub-track={options.sub_track}".encode())
                if options.burn_subtitles:
                    media_option(media, b":spu")
                    media_option(media, b":sout-spu")
                else:
                    # Track-selection variants carry video and the selected audio;
                    # subtitle-preserving remux support has not been established.
                    media_option(media, b":no-sout-spu")
                if options.seconds is not None:
                    media_option(media, f":stop-time={options.seconds}".encode())
                player = player_new(media)
                started = play(player)
                began = time.monotonic()
                deadline = began + options.timeout
                state = get_state(player)
                while state not in (6, 7) and time.monotonic() < deadline:
                    time.sleep(0.05)
                    state = get_state(player)
                stop(player)
                output_media = media_new(instance, str(output).encode())
                try:
                    output_tracks = inspect_tracks(vlc, output_media)
                finally:
                    media_release(output_media)
                for track_type, description in ((1, "video"), (0, "audio")):
                    if any(t["type"] == track_type for t in tracks) and not any(t["type"] == track_type for t in output_tracks):
                        raise RuntimeError("VLC output is missing " + description + "; it will not be published")
                results.append({"mux": mux, "start_result": started, "end_state": state,
                                "bytes": output.stat().st_size if output.exists() else 0,
                                "seconds": round(time.monotonic() - began, 3), "log": str(log),
                                "input": str(source), "output": str(output),
                                "audio_track": audio_index, "subtitle_track": options.sub_track,
                                "source_tracks": tracks, "subtitle_position": position,
                                "output_tracks": output_tracks,
                                "audio_track_id": options.audio_track_id,
                                "subtitle_burn_requested": options.burn_subtitles,
                                "requested_duration": options.seconds})
            finally:
                if player:
                    player_release(player)
                media_release(media)
                release(instance)
        result_file = options.output.with_suffix(options.output.suffix + ".result.json") if options.output else target / "results.json"
        result_file.write_text(json.dumps(results, indent=2))
        print(json.dumps(results, indent=2))
        if any(result["start_result"] != 0 or result["end_state"] != 6 or result["bytes"] == 0 for result in results):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
