# Codec samples staged for TV testing

Seven original-format copies covering eight test cases are available at:

`VLC Shared Library > TV Test > Codec Samples`

| File | Test |
| --- | --- |
| 01 - HEVC 10-bit.mkv | 10-bit HEVC video |
| 02 - HEVC 8-bit.mkv | 8-bit HEVC video |
| 03 - AC3 surround.mkv | AC-3 surround audio |
| 04 - EAC3 surround and ASS subtitles.mkv | E-AC-3 surround audio and ASS subtitles |
| 05 - Mono audio.mp4 | Mono sound |
| 06 - Bitmap subtitles.mp4 | Embedded bitmap subtitles |
| 07 - Multiple audio tracks.mp4 | Default/selected audio tracks |

The files were copied from the selected inventory candidates under
`J:\0001 media\TV Shows`. Sources were opened read-only and remain in place.
Each project copy was verified against a SHA-256 digest calculated while reading
its source; source size and modification time were unchanged after each copy.
The mapping and digests are in `build/TV Test/Codec Samples/copy-manifest.json`.

No remuxing or transcoding was performed on these copies. The J: library was not
added to sharing; only the existing project test folder is shared.
The helper was rescanned and its live ContentDirectory response was checked to
confirm that all seven files are listed. Roku may need its folder view reopened.
## Results reported by the user

All seven files played on the TCL 55S20. A couple initially appeared to lack
pause/rewind, but those controls became available after a few seconds. The user
noticed this behavior and retested the apparent failures, confirming it on those
files too. Allow playback to settle before recording a control failure. The
precise trigger and which files were delayed have not been instrumented.

This establishes direct-play compatibility for these specific video/audio
samples, including 8-bit/10-bit HEVC and surround-coded audio. It does not
establish speaker output channel count, passthrough behavior, or subtitle support.
Long pause/resume, late seeking and multiple physical devices remain separate
checks.

### Audio tracks

For number 7, the user reported English was selected. Inspection shows that
both MP3 stereo tracks are tagged `eng`; the first is marked default and the
second is not. This sample tests multiple audio tracks but cannot demonstrate
choosing English over another language. The user subsequently reported no audio
track-switching control in Roku Media Player for this MP4. A full compressed
audio SHA-256 comparison also established that both Scrubs tracks are exact
duplicates, so they cannot demonstrate an audible track difference.

VLC's automatic selection skipped the disabled second MP4 track. A scratch
copy with that track's enabled bit set was used to investigate selection; the
original project fixture and J: source were not edited. This is a test utility,
not an automatic production track-selection implementation.

### Subtitles

Number 6 (King of the Hill) played without visible subtitles. Its source has
an English `dvd_subtitle` bitmap track embedded in MP4, marked default but not
forced. The user confirmed the TV's captions were always on, but no captions
were seen. Packet inspection shows actual subtitle images are present. The
first dialogue subtitle starts at approximately 34.5 seconds, so the test must
include that part of the video before concluding that rendering is unsupported.

[Roku's Media Player documentation](https://support.roku.com/article/share-media-over-usb-or-network)
describes embedded subtitles in MKV and SRT/VTT sidecars. It does not establish
compatibility for this bitmap-in-MP4 combination. An explicitly selected VLC
subtitle burn-in test was generated from the project copy and visually verified
at 40 seconds, where the captions are present in the encoded picture. This
fallback re-encodes video to H.264 and retains the original MP3 audio. Do not re-encode all video
merely because one subtitle format is unsupported. ASS subtitle rendering in
number 4 has not been verified separately.

## Track Tests folder

Four additional fixtures are available under `TV Test > Track Tests`:

- `King of the Hill - Captions Burned In - 2 min.mkv`: VLC overlays the selected
  DVD subtitles into the video. Inspect near 40 seconds; captions cannot be
  toggled off in this test version. Output was visually checked locally; The user confirmed captions on the physical TV.
- `Multi Audio - Original.mkv`: an unchanged project copy of a Chappelle's Show
  featurette containing AC-3 and HE-AAC English stereo tracks. This provides a
  native MKV audio-track menu comparison with Scrubs' MP4.
- `Multi Audio - Selected AC3 - 2 min.mkv`: VLC remux with AC-3 selected.
- `Multi Audio - Selected AAC - 2 min.mkv`: VLC remux with AAC selected.

The selected-audio outputs were independently checked: each has exactly one
audio track, with the requested codec, and preserved HEVC video. Neither audio
selection variant re-encodes the video. This proves server-side selection for
the test MKV even if Roku offers no in-player track menu. These prepared files
are a prototype demonstration, not yet virtual resources generated on demand.
`scripts/stage-track-tests.py` validates the tracks before publishing fixtures.


## Confirmed track-test results and preferences

The user confirmed that the burned captions work. Some source cues move between
upper and lower positions; a separately rendered bottom-edge version was checked
locally at 40 seconds and stays at the bottom. The plugin now exposes position
preferences. Font/size/bold/color/outline were visually verified with a generated
plain-text SRT fixture rendered through VLC (18px Arial white versus 40px bold
Courier New yellow). Bitmap lettering cannot be restyled by these text settings.

The multi-audio MKV offered English Dolby and another English audio entry. Both
single-track AAC and AC-3 variants played, and the user reported pause, rewind
and fast forward on all these tests. A single menu entry means one audio track;
ffprobe confirms both source choices and the prepared variants are stereo.
Speaker/passthrough output channel counts were not measured.

For new preparations, the default preference selects existing English Dolby
when available, with file-default and English-AAC alternatives. It does not
synthesize Dolby or choose a foreign-language Dolby track over English.
