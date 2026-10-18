# Kami-Serv

### Your media library, shared from VLC to the screens around your home.

**Kami-Serv is a Windows UPnP/DLNA media server with a control panel inside VLC.** Choose the folders you want to share, give them names that make sense on your TV, and browse them from a compatible television, tablet, or phone. Each device opens its own stream and controls its own playback.

For files that need preparation, Kami-Serv uses your installed VLC through LibVLC to create a separate MKV, select an existing audio track, or burn subtitles into the video. Your original files stay intact.

**Current release: Windows alpha · VLC-powered preparation · No Python requirement**

[Getting started](#getting-started) · [Features](#what-you-can-do) · [How it works](docs/how-it-works.md) · [Build from source](#build-from-source) · [Testing and feedback](#testing-and-feedback)

## Why Kami-Serv?

The idea starts with something familiar: VLC already lives on many people's PCs and brings a broad collection of media codecs with it. Kami-Serv adds a way to put a selected library on the home network and manage that sharing from VLC.

A TV can watch one episode while a phone opens something else. Pausing or seeking on one device leaves the other stream alone. Files that your player already supports can be served directly; preparation is available when a different container, audio selection, or visible subtitles are useful.

The current alpha has two playback paths: **serve the original file** or **explicitly prepare a new MKV and share that**. Automatic per-device conversion is a future goal.

## What you can do

| Feature | What it means at home |
| --- | --- |
| **Share multiple folders** | Add movies, shows, music, or photos from locations you choose. |
| **Label and filter each share** | Display names such as Movies or Family Photos, with video, music, photo, or all-media filters. |
| **Serve several devices** | Clients receive independent HTTP streams rather than sharing a single playback position. |
| **Keep remote-control playback** | Compatible players can pause, resume, fast-forward, and rewind using seekable file delivery. |
| **Prepare files with VLC** | Create a two-minute preview or a full-length MKV without changing the source. |
| **Choose an audio preference** | Prefer an existing English Dolby or AAC track, or let VLC use the file's default selection. |
| **Burn in subtitles** | Make selected embedded subtitles visible even when the TV cannot display that subtitle format. |
| **Adjust subtitle presentation** | Choose top, bottom, or authored position with an offset; style supported text subtitles. |
| **Name your server** | Customize the advertised server name and supply an icon for clients that display it. |
| **Set up Windows Firewall access** | Use the installer option or the VLC repair button to configure access on Private networks. |
| **Inspect network activity** | Refresh a list of active and recent requests to help diagnose playback and discovery. |

**VLC's codec support powers preparation; the receiving device still determines what it can play directly.** A successful playback on one TV does not guarantee the same format works on every other model.

## Getting started

### Requirements

For the current alpha, install:

- **Windows 10 or 11, x64** — the current target platform.
- **[Desktop VLC 3.x, 64-bit](https://www.videolan.org/vlc/)**.
- **[.NET 8 ASP.NET Core Runtime, Windows x64](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)**. Choose the ASP.NET Core Runtime; the basic .NET Runtime or Desktop Runtime alone is insufficient.

**You do not need Python, FFmpeg, or the .NET SDK to use the installed application.** Python and ffprobe are used by some development checks only.

The PC and playback devices must be on a home network that permits them to communicate. The PC must stay awake and VLC must remain open while sharing.

### Install and share your first folder

1. Run the test installer provided by the project owner. The current build is named `LibraryShare-0.3.0-alpha.1-Setup.exe`.
2. Select your VLC installation folder if it differs from the detected location.
3. Leave **Allow sharing on Private networks** selected if you want setup to configure Windows Firewall. Approve the Windows administrator prompt when it appears.
4. Finish installation and open VLC. Choose **View > Share Library**.
5. On **Library folders**, click **Browse...**, choose a folder, enter a TV label, select its media filter, and click **Add / update folder**. Repeat for additional folders.
6. Click **Enable sharing**.
7. On your playback device, open a UPnP/DLNA browser, such as Roku Media Player or VLC for Android, and choose your server. Its initial name is **VLC Shared Library**.
8. Browse to a file and play it.

Start with a small folder containing a file your device can already play. After adding files outside the interface, click **Rescan files**; the TV may also need its folder view reopened.

> **Naming during the alpha:** The project is called **Kami-Serv**. The current interface still says **Share Library**, and installer filenames and internal components still use **LibraryShare**. These names refer to the same application.

### Make it yours

Open **Server & playback**, enter a server name such as **Kami-Serv — Living Room**, choose an icon, and click **Save server identity**. Clients may need to reopen their server list to refresh the name or icon. Icon display depends on the client.

Folder labels change how shares appear on your devices. They do not rename folders or files on disk.

## When a file needs preparation

On **Server & playback**, save your audio and subtitle preferences. Then open **Prepare for TV**, select a video, and choose a **two-minute preview** or **full-file preparation**. Enable **Burn subtitles into video** when needed and select the embedded subtitle track by its zero-based index.

Finished files appear in a separate **Prepared for TV** share. Refresh status to see completion, then browse to that share on the playback device.

- **Remuxing** changes the container to MKV while retaining the selected encoded streams. It avoids a video re-encode when burn-in is off.
- **Audio preferences** choose an existing English AC-3/E-AC-3 or AAC track when available. They do not synthesize Dolby audio, convert the audio codec, or change the channel count.
- **Subtitle burn-in** re-encodes the video as H.264 with the selected subtitles drawn into the picture. This takes more processing and makes those captions part of that prepared video.

Top and bottom placement also apply to supported bitmap captions. Font, size, bold, color, and outline controls apply to supported text subtitles; bitmap captions keep their drawn lettering, and ASS subtitles may retain authored styling. Preferences affect newly prepared files.

One preparation job runs at a time. Original and completed prepared files can still be served to several clients. See the [full explainer](docs/how-it-works.md) for the preparation workflow and its limits.

## Sharing follows VLC

Opening **View > Share Library** starts or attaches the installed helper. You can close the control panel and continue sharing while VLC stays open.

**Closing the last VLC instance attached to Kami-Serv stops the helper, active transfers, and preparation workers.** Clicking **Stop sharing** disables library delivery while VLC remains open. A device may continue briefly using content it has already buffered.

The server shares library files independently of VLC's playlist. A movie playing on a TV does not need to be playing in the PC's VLC window.

## Your files and your network

You explicitly choose the shared folders. Kami-Serv reads those originals and writes prepared versions to its own data directory. A fresh installation starts with **sharing off and no selected folders**; upgrades preserve the existing configuration.

The application operates on the local network without a cloud account. Treat an enabled share as available to other devices that can reach it on your home network: this alpha has no per-viewer login or permissions system. Management commands are separately protected by a local control credential and restricted to loopback access.

Windows Firewall setup creates rules for the helper executable:

| Purpose | Inbound port | Scope |
| --- | --- | --- |
| Library browsing and media delivery | TCP `57642` | Private networks, local subnet |
| UPnP/SSDP discovery | UDP `1900` | Private networks, local subnet |

Only firewall changes request administrator permission. Setup/repair does not change the network's Public/Private category, enable or disable Windows Firewall, or configure router port forwarding. The **Check firewall** and **Allow / repair firewall access** buttons are on **Server & playback**. Third-party firewall products may need their own configuration.

## Compatibility and alpha status

| Client or check | Evidence so far |
| --- | --- |
| **TCL 55S20 / Roku Media Player** | Physical-device playback confirmed across the tested original and remuxed samples; pause, fast-forward, rewind, selected audio variants, and burned captions were confirmed. |
| **VLC for Android** | Playback confirmed by the tester; device/version details and the full controls/audio/subtitle matrix have not been recorded. |
| **Four local LibVLC players** | Concurrent playback and independent pause/resume/seek checks passed on the development PC. |
| **Other TVs and multiple physical devices together** | Further testing needed. |

On some Roku samples, pause and seeking became available a few seconds after playback started. Waiting briefly and retrying resolved the apparent failures in those tests. No general requirement to remux every MP4 has been established.

The test history is recorded in [physical-device notes](docs/tv-test.md) and [codec sample results](docs/codec-samples.md). Kami-Serv is not a certified DLNA implementation.

### Current boundaries

- Preparation is manual. Automatic client profiling, on-demand live transcoding, hardware encoder selection, HDR conversion, and an FFmpeg fallback are not implemented.
- The server currently uses IPv4. Scanning is manual and synchronous, and the preparation selector shows the first 500 indexed videos.
- The activity list updates when refreshed. It shows HTTP requests, not an authoritative count of viewers or the TV's play/pause state. Recent history is held in memory for ten minutes, with at most 50 device/file entries.
- The default concurrency limit is 16 open HTTP requests. A player can make several requests, so this is not a 16-device promise. Capacity depends on the PC, storage, network, and workloads.
- The installer is an **unsigned alpha**. Extraction, isolated installation/upgrade/removal, helper lifecycle, and preparation are tested. Interactive setup layout, Windows Apps registration, and live UAC/firewall changes still need manual validation.

## Build from source

Building requires the **.NET 8 SDK**, desktop VLC, and Windows' .NET Framework C# compiler. The server currently has no external NuGet package dependencies. The private repository requires GitHub access.

```powershell
git clone https://github.com/ineedliang/Kami-Serv.git
cd Kami-Serv
.\build-installer.cmd
```

Or run the build script directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-installer.ps1
```

Output:

```text
build/dist/LibraryShare-0.3.0-alpha.1-Setup.exe
build/dist/LibraryShare-0.3.0-alpha.1-Setup.exe.sha256
```

Only the EXE is needed to install; the companion checksum supports file verification. The installer payload excludes developer share settings, credentials, test media, Python, and VLC binaries. VLC and the ASP.NET Core Runtime are installed separately.

For an isolated development preview, use `preview-share.cmd`. It creates a separate VLC profile under `build/vlc-preview`; close that VLC window to stop the preview helper. `preview-share.cmd -LocalOnly` keeps the preview on loopback. The older `install-vlc-plugin.cmd` installs directly into the current user's normal VLC profile.

See [build tools and relocation notes](docs/build-tools.md) for the tool inventory and local development conventions.

### Publish this working folder to GitHub

The project owner can run `publish-to-github.cmd` to commit the source and documentation to the private repository. Git's credential manager may request a GitHub sign-in. The script fetches existing history, checks the staged file list, and pushes without force. It verifies that the remote commit matches the local one before reporting success. A diverged branch requires review before the script will publish.

Build output, runtime settings, credentials, logs, and playback fixtures are excluded. Installer binaries stay in `build/dist`; distribute a checked installer separately from the source repository. The script uses your existing Git author identity, or a project-local fallback for that commit if no identity is configured.

## Testing and feedback

Useful reports include the TV/device model, player app and version, video/audio codecs and container, whether you played an original or prepared file, and what happened when you tried pause, seek, audio selection, or subtitles. For discovery problems, include the firewall status shown in the panel. Remove private paths, filenames, addresses, and credentials from logs before sharing them.

Report findings through [GitHub Issues](https://github.com/ineedliang/Kami-Serv/issues), subject to access to this private repository. Media files, device serial numbers, and hardware IDs are not needed for a basic report.

For contributors, the development checks use Python; some preparation checks also need local fixture media and ffprobe. Test outputs stay under `build/`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
python tests/integration.py
python tests/libvlc_smoke.py
python tests/preparation_smoke.py
python tests/installation_smoke.py
python tests/picker_smoke.py
python tests/firewall_smoke.py
python tests/installer_package_smoke.py
```

Build the installer before running the package check. Firewall tests use an in-memory policy and a stub for elevation; they do not change the live Windows firewall. Installation tests use isolated folders rather than the normal VLC profile. Preparation and package checks also run with Python absent from the application's PATH.

## Where the project is heading

The next steps are broader physical-device testing, a consistent Kami-Serv name across the interface and installer, setup/UAC validation and signing, and richer device compatibility profiles. Longer-term work includes automatic selection between original delivery and conversion, independent live transcoding sessions, hardware encoding options, and an optional FFmpeg fallback where useful.

These are development goals, not features included in the current alpha.

---

Kami-Serv is an independent project built around VLC and LibVLC. It is not an official VideoLAN product. VLC and the other technologies referenced here belong to their respective projects. Repository access does not itself grant redistribution rights; the project's license needs to be selected and documented before public distribution.
