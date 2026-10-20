# Kami-Serv

**Share selected folders from VLC with TVs, phones, and tablets on your home network.**

Kami-Serv is a Windows UPnP/DLNA media server with its control panel in VLC. Choose the folders to share, name them for the people using your TV, and browse them from a compatible player. Files are normally delivered directly from the original; optional VLC-powered preparation can create a separate MKV without changing that original.

> **Windows alpha.** Kami-Serv is ready for hands-on testing, not yet a finished media-server product. It is currently tested with a TCL Roku TV through Roku Media Player, VLC for Android, and local LibVLC players.

[Get started](#get-started) · [Features](#features) · [Compatibility](#compatibility) · [Build from source](#build-from-source) · [How it works](docs/how-it-works.md)

## What it does

- Shares only folders you explicitly select.
- Lets several devices stream independently; one device's pause or seek does not affect another.
- Adds labels such as **Movies**, **TV Shows**, or **Family Photos** to make a library easier to browse.
- Serves original files over HTTP with byte-range support for compatible players.
- Uses VLC/LibVLC to prepare a separate MKV when remuxing, audio selection, or burned-in captions are useful.
- Finds matching external SRT captions and publishes them with a video where compatible players support them.
- Keeps prepared files separate from the originals.
- Provides local-only management controls, a private-network firewall helper, and basic request activity.

Kami-Serv does not upload media or require an account. It serves files on the local network while sharing is enabled.

Direct playback is the normal path and has worked for the library used during development. Preparation is available for a file that needs a different container, audio choice, or burned-in captions; it is not required for ordinary sharing.

## Get started

### Requirements

- Windows 10 or 11, x64
- [Desktop VLC 3.x, 64-bit](https://www.videolan.org/vlc/)
- [.NET 8 ASP.NET Core Runtime, Windows x64](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)

Use the **ASP.NET Core Runtime** on the .NET download page. The basic .NET Runtime and Desktop Runtime alone are not enough.

### Install

1. Download the current installer from [Releases](../../releases).
2. Run the installer and choose your VLC folder if the detected one is wrong.
3. Leave **Allow sharing on Private networks** selected if you want Kami-Serv to set up Windows Firewall access. Windows will ask for administrator approval only for that firewall change.
4. Open VLC and choose **View > Share Library**.
5. On **Library folders**, choose **Browse...**, select a folder, enter its TV label, choose a media filter, and select **Add / update folder**.
6. Select **Enable sharing**.
7. In a compatible player on the same network, open the server. Its initial name is **VLC Shared Library**.

Start with a small folder containing a file your device already plays. After adding files outside the panel, choose **Rescan files** and reopen that folder in the player if necessary.

The PC must remain awake and VLC must stay open while sharing. Closing the last VLC instance attached to Kami-Serv stops the helper, active transfers, and preparation jobs.

## Features

| Feature | Details |
| --- | --- |
| Folder sharing | Share movies, shows, music, photos, or mixed folders; name and filter each one. |
| Independent playback | Every client receives its own seekable stream and controls its own playback position. |
| Optional VLC-powered preparation | Make a two-minute preview or a full prepared MKV only when a file needs it; the source stays untouched. |
| Audio preference | Prefer an existing English Dolby or AAC track, or keep VLC's file-default choice. |
| Captions | Publish matching SRT sidecars; copy one alongside a prepared video; or burn captions into the picture. |
| Subtitle presentation | Set position, offset, font, size, bold, color, and outline for supported text captions burned into new output. |
| Server identity | Set the server name and import an icon for players that show one. |
| Network help | Check or repair the app's private-network firewall rules from VLC. |
| Activity view | Inspect active and recent HTTP requests while diagnosing discovery or playback. |

## Captions

Keep an SRT beside its video with the same base filename. Language tags work too:

```text
Movies/
  Example Movie.mp4
  Example Movie.srt
  Example Movie.eng.srt
  Example Movie.spa.srt
```

Choose **Rescan files** after adding captions. Kami-Serv associates the sidecars with their video instead of adding them as standalone videos. A plain same-name SRT is offered first, followed by English-tagged captions and then other languages.

To use a caption while preparing a file, select the video in **Prepare for TV**, choose **Load SRTs for selected video**, and select the desired source:

- With **Burn subtitles into video** off, Kami-Serv copies the SRT beside the prepared MKV as a switchable external caption.
- With it on, VLC draws the caption into the video. This re-encodes video and makes the captions permanently visible.

Use UTF-8 SRTs for dependable character display. SRT delivery depends on the receiving player's subtitle support; if a player does not show the sidecar, use burn-in. See the [SRT test checklist](docs/srt-testing.md) for known behavior and device testing.

## Compatibility

| Client or check | Current evidence |
| --- | --- |
| TCL 55S20 / Roku Media Player | Original and remuxed playback, pause, seek, audio variants, and burned-in captions were tested on a physical device. |
| VLC for Android | Playback was confirmed; the complete controls and subtitle matrix still needs recording. |
| Four local LibVLC players | Concurrent streams with independent pause, resume, and seek were checked. |
| Other TVs and several physical devices at once | Testing needed. |

The player determines whether it can decode a file delivered directly. A successful file on one TV does not guarantee it will work on another. Kami-Serv is not DLNA certified.

On some Roku samples, pause and seeking were available a few seconds after playback began. Retrying after that delay worked in testing. See [device notes](docs/tv-test.md) and [codec sample results](docs/codec-samples.md).

## Security and network behavior

Kami-Serv starts with sharing disabled and no folders selected. It serves only indexed files in the folders you choose and keeps management commands on loopback behind a local control credential.

Enabling sharing makes those selected files available to devices that can reach the PC on your local network. There is no per-person login or permissions system in this alpha. Use it on a network whose reachable devices you trust.

The optional firewall setup creates rules for the helper only on Private networks and only for the local subnet:

| Purpose | Port | Protocol |
| --- | ---: | --- |
| Library browsing and media delivery | 57642 | TCP |
| Discovery | 1900 | UDP |

The setup does not change your Windows network category, change global firewall settings, or configure router port forwarding.

## Current limits

- Manual preparation only: no automatic device profiles, on-demand transcoding, hardware encoding choice, HDR conversion, or FFmpeg fallback.
- IPv4 only; scanning is manual and synchronous.
- The preparation selector lists the first 500 indexed videos.
- The activity list reports HTTP requests, not a viewer count or the TV's exact play/pause state.
- Default request concurrency is 16 open HTTP requests. A player may use more than one request.
- The installer is unsigned during the alpha.

Future work includes a more integrated VLC interface, broader physical-device testing, playlist publishing from VLC, device profiles, live conversion, and improved configuration. These are goals, not current features.

## Build from source

Development builds require the .NET 8 SDK, desktop VLC, and Windows' .NET Framework C# compiler.

```powershell
git clone https://github.com/ineedliang/Kami-Serv.git
cd Kami-Serv
.\build-installer.cmd
```

The installer is written to:

```text
build/dist/LibraryShare-0.3.0-alpha.2-Setup.exe
build/dist/LibraryShare-0.3.0-alpha.2-Setup.exe.sha256
```

For an isolated development preview:

```powershell
.\preview-share.cmd
```

That command creates a separate VLC profile under `build/vlc-preview`. Add `-LocalOnly` to keep the preview server on loopback. See [build tools](docs/build-tools.md) for details.

### Tests

The installed application has no Python dependency. Python and, for some checks, `ffprobe` are development-only tools.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
python tests/integration.py
python tests/libvlc_smoke.py
python tests/preparation_smoke.py
python tests/srt_smoke.py
python tests/installation_smoke.py
python tests/picker_smoke.py
python tests/firewall_smoke.py
python tests/installer_package_smoke.py
```

Build the installer before running the package check. The firewall tests use an in-memory policy and do not change the live Windows firewall.

## Contributing and feedback

Bug reports are most useful with:

- TV or device model and player app/version
- Video container and video/audio codecs
- Whether you streamed the original or a prepared version
- What happened during playback, pause, seek, audio selection, or subtitle selection
- The firewall status shown in the control panel for discovery issues

Please remove private paths, filenames, IP addresses, credentials, and media files before posting logs or screenshots. Open an [issue](../../issues) with the details.

## Project names

**Kami-Serv** is the public project name. The current alpha still uses **Share Library** in VLC and **LibraryShare** in installer filenames and internal paths. They refer to the same application.

## License

Kami-Serv is licensed under the [GNU General Public License v3.0 or later](LICENSE).

## Credits

Kami-Serv is an independent project built around VLC and LibVLC; it is not an official VideoLAN product. VLC and LibVLC belong to the VideoLAN project.
