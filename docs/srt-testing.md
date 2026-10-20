# SRT test checklist

This build adds external SRT sidecars without a new runtime dependency. The .NET
helper and VLC perform preparation; originals remain read-only.

## Try on Roku Media Player

1. Install the alpha 2 build and reopen VLC. Existing shared folders/settings are preserved.
2. Choose a known-playable video in a small test folder. Put an SRT beside it with
   the same base name, for example `Example Movie.mp4` and `Example Movie.srt`.
   Language variants such as `Example Movie.eng.srt` also match. UTF-8 is recommended.
3. Add that folder if it is not shared, click **Rescan files**, then reopen the
   folder/server view in Roku Media Player.
4. Play the original video. Wait a few seconds and use **Star** to look for the
   subtitle/caption choice; on Roku TV it may be under **Accessibility**.
5. Check a known dialogue cue, pause/resume, seek forward, then seek backward.
   Note whether captions can be toggled off and whether multiple languages appear.
6. Refresh activity in VLC. An SRT request can appear as a recent request even
   after the small caption download finishes. No request does not establish why
   the player ignored it; record the client behavior alongside the metadata test.

## Check preparation

Select the video in **Prepare for TV**, click **Load SRTs for selected video**,
and choose the filename under **Subtitle source**.

- Prepare a preview with **Burn subtitles into video** unchecked. The result is
  an MKV plus the selected SRT under **Prepared for TV**. Check native captions.
- Prepare another preview with burn-in checked. Check visible captions at a known
  cue. These captions are permanent in that prepared version. Font, position,
  size, bold, color and outline preferences affect this path.

The two-minute preview retains the beginning of the video; use a cue within its
first two minutes. Full-file preparation is available for later cues.

## Evidence recorded so far

`python tests/srt_smoke.py` generates its own short video and SRT under `build/`.
It checks matching/languages, primary caption metadata, HTTP GET/HEAD/ranges,
protection against unrelated/hidden/oversized files, sharing revocation, SRT copy,
and actual bright caption pixels on a black source frame after LibVLC burn-in.
It also exercises the Lua selection controls with VLC's actual HTTP/XML runtime
and checks that the original source sizes, times and hashes stay unchanged.
Python is absent from the application's PATH during this check. The test itself
uses development Python and `_kit` ffmpeg/ffprobe for generating/verifying fixtures.

The generated frame has been visually inspected locally. Physical Roku/Android
subtitle discovery and language switching have **not yet been confirmed** for
this build. Existing video playback confirmations do not establish SRT support.

Reference: [Roku Media Player subtitle guidance](https://support.roku.com/article/share-media-over-usb-or-network).
