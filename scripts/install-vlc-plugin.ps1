param(
    [string]$VlcDirectory = 'C:\Program Files\VideoLAN\VLC',
    [string]$Destination = (Join-Path $env:APPDATA 'LibraryShare'),
    [string]$ExtensionDirectory = (Join-Path $env:APPDATA 'vlc\lua\extensions'),
    [switch]$NoLaunch,
    [switch]$ConfigureFirewall,
    [switch]$MigrateDevelopmentSettings,
    [switch]$RegisterApplication,
    [switch]$DesktopShortcut
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$projectRoot = Split-Path -Parent $PSScriptRoot
$package = if (Test-Path -LiteralPath (Join-Path $projectRoot 'server\LibraryShare.Server.dll')) { $projectRoot } else { Join-Path $projectRoot 'build\package' }
if (-not (Test-Path -LiteralPath (Join-Path $package 'server\LibraryShare.Server.dll'))) { & (Join-Path $PSScriptRoot 'package.ps1') }
. (Join-Path $PSScriptRoot 'check-prerequisites.ps1') -VlcDirectory $VlcDirectory
$dependencies = Get-LibraryShareDependencies $VlcDirectory
$dotnet = $dependencies.Dotnet
if ($RegisterApplication -or -not $NoLaunch) {
    $installedToken = Join-Path $Destination 'build\library.json.control-token'
    if ((Test-Path -LiteralPath (Join-Path $Destination 'runtime.json')) -and (Test-Path -LiteralPath $installedToken)) {
        try {
            $token = (Get-Content -LiteralPath $installedToken -Raw).Trim()
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:57642/local?token=$token&action=shutdown" -TimeoutSec 2 | Out-Null
            $pidFile = Join-Path $Destination 'build\helper.pid'
            if (Test-Path -LiteralPath $pidFile) {
                $helperPid = [int](Get-Content -LiteralPath $pidFile -Raw)
                $helper = Get-Process -Id $helperPid -ErrorAction SilentlyContinue
                if ($helper -and $helper.Path -eq (Join-Path $Destination 'server\LibraryShare.Server.exe')) {
                    if (-not $helper.WaitForExit(8000)) { throw 'Helper is still stopping. Close VLC and rerun setup.' }
                }
            }
            Start-Sleep -Milliseconds 300
        } catch { }
    }
    $connection = New-Object Net.Sockets.TcpClient
    try {
        try { $connection.Connect('127.0.0.1',57642) } catch { }
        if ($connection.Connected) { throw 'Close the Library Share preview / running helper before installing. Your TV playback will stop during installation.' }
    } finally { $connection.Dispose() }
}
$Destination = [IO.Path]::GetFullPath($Destination)
$ExtensionDirectory = [IO.Path]::GetFullPath($ExtensionDirectory)
New-Item -ItemType Directory -Path $Destination,$ExtensionDirectory,(Join-Path $Destination 'build') -Force | Out-Null
foreach ($name in @('server','scripts','vlc')) { Copy-Item -LiteralPath (Join-Path $package $name) -Destination $Destination -Recurse -Force }
$legacyWorker = Join-Path $Destination 'scripts\probe-vlc-remux.py'
if (Test-Path -LiteralPath $legacyWorker) { Remove-Item -LiteralPath $legacyWorker }
# Public installs start empty and OFF. Migration is explicit and development-only.
if ($MigrateDevelopmentSettings) { foreach ($name in @('library.json','library.json.control-token','library.json.playback.json')) {
    $source = Join-Path $projectRoot "build\$name"
    $target = Join-Path $Destination "build\$name"
    if ((Test-Path -LiteralPath $source) -and -not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath $source -Destination $target }
} }
@{ VlcDirectory = $VlcDirectory; Dotnet = $dotnet; ExtensionDirectory = $ExtensionDirectory } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Destination 'runtime.json') -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $Destination 'vlc\library_share.lua') -Destination (Join-Path $ExtensionDirectory 'library_share.lua') -Force
# Bootstrap immediately, even when setup finishes without launching VLC. No server or scan starts here.
$configPath = Join-Path $Destination 'build\library.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    @{Name='VLC Shared Library';Id=[Guid]::NewGuid().ToString();Enabled=$false;Folders=@();FolderSettings=@{};MaxConcurrentTransfers=16} |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8
}
$tokenPath = $configPath + '.control-token'
if (-not (Test-Path -LiteralPath $tokenPath)) {
    $random = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($random) } finally { $rng.Dispose() }
    [IO.File]::WriteAllText($tokenPath,([BitConverter]::ToString($random)).Replace('-',''),(New-Object Text.UTF8Encoding($false)))
}
$token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
if ($token -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid installed control credential. Existing settings were preserved.' }
$encodedRoot = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Destination))
$code = '$root=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(''' + $encodedRoot + ''')); & (Join-Path $root ''scripts\launch-helper.ps1'')'
$startCommand = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand ' + [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
$modules = Join-Path $ExtensionDirectory 'modules'
New-Item -ItemType Directory -Path $modules -Force | Out-Null
$lua = 'return { port = 57642, token = "' + $token + '", start_command = "' + $startCommand + '", manage_lifetime = true }' + "`n"
[IO.File]::WriteAllText((Join-Path $modules 'library_share_config.lua'),$lua,(New-Object Text.UTF8Encoding($false)))
if ($ConfigureFirewall) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Destination 'scripts\configure-firewall.ps1') -Action Allow
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Application installed. Firewall setup failed; retry Allow / repair firewall access in VLC.' }
    # Firewall permission can be cancelled without undoing the application install.
}
& (Join-Path $Destination 'scripts\register-application.ps1') -InstallDirectory $Destination -DesktopShortcut:$DesktopShortcut -SkipRegistration:(-not $RegisterApplication)
if (-not $NoLaunch) {
    $vlcProcess = Start-Process -FilePath (Join-Path $VlcDirectory 'vlc.exe') -ArgumentList '--no-one-instance' -WindowStyle Normal -PassThru
    & (Join-Path $Destination 'scripts\launch-helper.ps1') -OwnerPid $vlcProcess.Id -OwnerStarted ($vlcProcess.StartTime.ToUniversalTime().Ticks)
}
Write-Host "Installed for your Windows account: $Destination"
Write-Host 'In the newly opened VLC window, choose View > Share Library.'
Write-Host 'Library folders: Browse (the selected path fills automatically), enter a TV label, choose the media type, then Add / update folder.'
Write-Host 'Server & playback: change the server name, choose an icon, and save.'
Write-Host 'Opening Share Library starts its helper. Closing VLC stops the helper and TV transfers.'
