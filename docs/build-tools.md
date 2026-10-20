# Build tools and relocation

Prefer existing tools in `G:\.0000PROJECTS\_kit`. Any additional downloaded tool
must stay under this project root (for example `tools\incoming\ToolName`) until
the user's other agent relocates it into `_kit`. Do not install additional build
tools globally or write to `_kit` from this project. Record its source, version,
hash, current path and scripts referencing it here if one is added.

No new build tools were downloaded for this alpha. The attempted Inno Setup
download failed because this session's configured network proxy was unavailable;
no compiler installer was run. The build instead uses tools already on Windows:

| Tool | Current source | Used by |
| --- | --- | --- |
| .NET SDK 8 | `dotnet.exe` on PATH | `scripts/build.ps1`, `scripts/package.ps1` |
| Windows C# compiler / .NET Framework | `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` | `scripts/build-installer.ps1` |
| Windows PowerShell 5.1 | Windows component | Setup, launcher, dialogs, firewall management |
| Desktop VLC 3.x x64 | User-selected VLC folder | Runtime codecs and native preparation |
| Python 3.11+ | Existing developer installation | Development scripts/tests only; not distributed or required by the app |
| ffprobe | `_kit\shared\ffmpeg\2026-08-17-full_build-gyan\ffprobe.exe` | Independent test output validation only |

`build-installer.cmd` produces `build\dist\LibraryShare-0.3.0-alpha.2-Setup.exe`
using an allowlist of release files. The setup program is built from
`src\LibraryShare.Setup\Setup.cs` with an embedded ZIP and an `asInvoker` manifest.
It installs per user; only the firewall command requests elevation. No Python,
FFmpeg, LibVLC DLLs, VLC plugins, development config, tokens or test media are
included in its payload. The tester supplies installed VLC and the .NET 8 ASP.NET
Core Runtime, both x64. Code signing and manual setup/UAC validation remain before
a public release.
