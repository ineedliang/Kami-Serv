# First physical TV test

Date: 2026-10-18

- Target: TCL 55S20 using Roku Media Player on the home network.
- Shared content: only the generated clip in `build/TV Test/`.
- Clip: 120 seconds, 1280x720 at 30 fps, H.264 Constrained Baseline / level 3.1,
  yuv420p, AAC stereo, MP4 with metadata at the beginning.
- The user confirmed that the test pattern plays on the TV.
- Four simultaneous LibVLC players on the PC also played the served MP4 and
  passed independent pause, resume, forward seeking and backward seeking.
  This verifies concurrent video sessions locally; it is not a measurement of
  four physical devices or available Wi-Fi capacity.
- The TV responds to discovery and basic device queries. Its playback-state
  and app-list queries returned HTTP 403. No TV access settings were changed.
- A second TV was unavailable for testing; that check is deferred.

## Container comparison and playback controls

- The user reported that the original MP4 played but could not be paused.
- At that point the shared test folder contained only the MP4; there was no
  MKV in the server's list yet. This was confirmed through both the filesystem
  and the live ContentDirectory response.
- Added `Library Share - TV Test.mkv` by remuxing the MP4's existing streams
  without re-encoding, then explicitly rescanned the library. The live server
  now lists both files.
- After being asked to play the MKV, the user confirmed pause, fast forward,
  and rewind work on the physical TV.
- This supports a container/metadata compatibility hypothesis. It does not
  establish why the original MP4 fails or confirm that the MP4 is now fixed.
- The server currently omits duration metadata from ContentDirectory entries;
  publishing probed media metadata is a candidate improvement to investigate.

Still to verify: long pause/resume, the original MP4 after any compatibility
changes, and multiple physical devices. Filesystem changes still require a
rescan in this prototype; Roku may also need its folder view reopened.
Automatic per-device remuxing and transcoding are not implemented yet.
No personal media folders were shared.

## Installed VLC remux capability

`scripts/probe-vlc-remux.py` exercised the installed VLC 3.0.21 through LibVLC,
without invoking a transcoder or a separate FFmpeg executable for the remux.
Both `mkv` and explicit `avformat{mux=matroska}` output produced valid Matroska
files containing H.264 video and AAC audio. An MPEG-TS remux also succeeded.
An independent ffprobe check identified the actual output containers and codecs.
The Matroska output reports 119.933 seconds versus the input's 120.000 seconds;
timestamp and end-of-stream behavior need validation before production use.

The explicit Matroska output is now shared as
`Library Share - VLC Remux Test.mkv`. Physical-TV controls on this VLC-generated
version still need verification. The earlier user-confirmed MKV was produced
with FFmpeg stream copy as a container comparison.

This proves the installed VLC can perform the needed H.264/AAC-to-MKV remux.
It does not establish support for arbitrary codecs, subtitle types, containers,
or playback devices. Automatic selection and worker integration remain to build.

## User-provided samples

The user copied an MP4 and an AVI into the project root for testing. Those source
files were left unchanged. Copies of just those two files were placed under
`build/TV Test/Your Samples/Originals/`; the project root itself was not shared.
Full-length VLC remuxes were placed under `Your Samples/VLC Remuxed/`.
The live server was rescanned and now lists seven media files in the test share.

| Sample | Source streams | VLC MKV output | Source / output duration |
| --- | --- | --- | --- |
| Vikings | H.264 Main 640x360, AAC stereo 48 kHz | Same codec types and resolution, valid Matroska | 2655.723 / 2655.652 seconds |
| Top Gear | MPEG-4 Advanced Simple Profile 512x328, MP3 stereo 32 kHz | Same codec types and resolution, valid Matroska | 2894.652 / 2894.640 seconds |

Both remuxes used the installed VLC's `avformat{mux=matroska}` output without
the transcoder. Output codecs, dimensions, container, and approximate duration
were checked independently with ffprobe. Remuxing took about 2 seconds for the
MP4 and 42 seconds for the AVI in this run. These are test observations, not
performance guarantees or a full frame/sample-integrity check.

After testing the two VLC-remuxed samples, the user reported that both worked
well on the physical TCL 55S20 through Roku Media Player. This establishes
successful playback for these particular H.264/AAC and MPEG-4 ASP/MP3 samples
inside MKV. The AVI did not require video transcoding in this test.

Treat this device-specific evidence as stronger than an inference from Roku's
general format list for these tested combinations. It does not establish
compatibility for every MPEG-4 ASP feature, resolution, audio track, or TV model.
The user subsequently clarified that the original Vikings MP4 and both VLC
remuxes allow pause, fast forward, and rewind. They also retested the original
generated test-pattern MP4 and confirmed that its controls now work too.
No changes were made to that test-pattern MP4 between the failed and successful
reports; files were added and the server library rescanned. The trigger is
unknown, and a Roku refresh/cache explanation remains a hypothesis.

These results invalidate treating MP4 in general as requiring MKV remuxing.
Keep direct playback as the first choice. Long pauses, end-of-file integrity,
and multiple physical devices remain separate checks.

The later seven-file codec sample set also played successfully. The user found
that pause/rewind become available only after a few seconds on some files and
retested the initial apparent failures. This observed startup delay is stronger
evidence than the earlier MP4/container hypothesis. Its underlying cause is
still unconfirmed. See [codec sample results](codec-samples.md) for the English
audio-track limitation and bitmap subtitle burn-in results.


The user later confirmed visible burned-in bitmap captions, selectable English
Dolby/AAC choices in the real multi-track MKV, successful single-track variants,
and pause/fast-forward/rewind in all Track Tests fixtures. Native MKV track-menu
availability differs from the duplicate-track Scrubs MP4. The new plugin now
includes explicit preparation controls and persistent preferences; no second
physical TV was available for concurrency testing.

## Additional client: VLC for Android

The user reported successful playback through VLC for Android. Together with
Roku Media Player on the TCL 55S20, this provides evidence from two different
client applications. The Android device model, VLC/Android versions, tested
files, subtitle/audio selection behavior, seeking, and simultaneous playback
with the TV were not specified. This does not yet establish compatibility with
other TVs' built-in players or constitute DLNA certification.
