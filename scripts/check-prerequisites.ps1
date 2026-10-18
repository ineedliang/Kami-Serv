param([string]$VlcDirectory = 'C:\Program Files\VideoLAN\VLC', [switch]$Json)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
function Get-LibraryShareDependencies {
    param([string]$VlcDirectory)
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Library Share requires 64-bit Windows 10 or 11.' }
    foreach ($file in @('vlc.exe','libvlc.dll','libvlccore.dll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $VlcDirectory $file))) { throw "Install desktop VLC 3.x (64-bit), or select its folder. Missing: $file" }
    }
    $stream = [IO.File]::OpenRead((Join-Path $VlcDirectory 'libvlc.dll'))
    $reader = New-Object IO.BinaryReader($stream)
    try {
        $stream.Position = 0x3c; $offset = $reader.ReadInt32()
        $stream.Position = $offset
        if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne 0x8664) { throw 'Install the 64-bit edition of VLC 3.x.' }
    } finally { $reader.Dispose(); $stream.Dispose() }
    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $VlcDirectory 'libvlc.dll')).FileVersion
    if ($version -notmatch '^3\.') { throw 'This alpha supports desktop VLC 3.x (64-bit).' }
    $dotnetCommand = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if (-not $dotnetCommand) { throw 'Install the .NET 8 ASP.NET Core Runtime (Windows x64), then reopen setup.' }
    $dotnet = $dotnetCommand.Source
    $dotnetStream = [IO.File]::OpenRead($dotnet)
    $dotnetReader = New-Object IO.BinaryReader($dotnetStream)
    try {
        $dotnetStream.Position = 0x3c; $dotnetOffset = $dotnetReader.ReadInt32()
        $dotnetStream.Position = $dotnetOffset
        if ($dotnetReader.ReadUInt32() -ne 0x4550 -or $dotnetReader.ReadUInt16() -ne 0x8664) { throw 'The .NET host on PATH must be 64-bit. Install the .NET 8 ASP.NET Core Runtime (Windows x64).' }
    } finally { $dotnetReader.Dispose(); $dotnetStream.Dispose() }
    $runtimes = & $dotnet --list-runtimes
    if ($LASTEXITCODE -ne 0 -or -not ($runtimes -match 'Microsoft.AspNetCore.App 8\.')) { throw 'Install the .NET 8 ASP.NET Core Runtime (Windows x64), then reopen setup.' }
    [pscustomobject]@{ VlcDirectory = [IO.Path]::GetFullPath($VlcDirectory); Dotnet = $dotnet }
}
if ($MyInvocation.InvocationName -ne '.') {
    try {
        $dependencies = Get-LibraryShareDependencies $VlcDirectory
        if ($Json) { @{Ready=$true;Message='VLC and .NET ASP.NET Core 8 are available.';Dependencies=$dependencies}|ConvertTo-Json -Compress }
        else { $dependencies }
    } catch {
        if ($Json) { @{Ready=$false;Message=$_.Exception.Message}|ConvertTo-Json -Compress; exit 1 }
        throw
    }
}
