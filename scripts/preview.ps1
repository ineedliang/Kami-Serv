param(
    [string]$VlcDirectory = 'C:\Program Files\VideoLAN\VLC',
    [string]$Address = '',
    [switch]$LocalOnly,
    [switch]$PrepareOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'build.ps1')
$previewDirectory = Join-Path $projectRoot 'build\vlc-preview'
$portableDirectory = Join-Path $previewDirectory 'portable'
$extensionDirectory = Join-Path $portableDirectory 'lua\extensions'
New-Item -ItemType Directory -Path $portableDirectory,$extensionDirectory -Force | Out-Null
# A small portable shell reuses the installed plugins and resources. All settings
# and extension files belong to this workspace, not the regular VLC profile.
foreach ($file in @('vlc.exe', 'libvlc.dll', 'libvlccore.dll')) {
    $sourceFile = Join-Path $VlcDirectory $file
    if (-not (Test-Path -LiteralPath $sourceFile)) { throw "Missing VLC component: $sourceFile" }
    Copy-Item -LiteralPath $sourceFile -Destination (Join-Path $previewDirectory $file) -Force
}
$server = Join-Path $projectRoot 'build\server\LibraryShare.Server.dll'
$listen = if ($LocalOnly -or $PrepareOnly) { '127.0.0.1' } else { '0.0.0.0' }
$serverArgs = @($server, '--project', $projectRoot, '--listen', $listen)
if ($Address -and -not $PrepareOnly) { $serverArgs += @('--advertise', $Address) }
$quotedArgs = ($serverArgs | ForEach-Object { '"{0}"' -f $_ }) -join ' '
$serverLog = Join-Path $projectRoot 'build\preview-server.log'
$serverErrorLog = Join-Path $projectRoot 'build\preview-server-error.log'
$helper = $null
$oldPlugins = $env:VLC_PLUGIN_PATH
$oldData = $env:VLC_DATA_PATH
try {
    $helper = Start-Process -FilePath (Get-Command dotnet).Source -ArgumentList $quotedArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $serverLog -RedirectStandardError $serverErrorLog -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($helper.HasExited) { throw "Library helper could not start. Check $serverErrorLog (another copy may already be running)." }
        if ((Test-Path -LiteralPath $serverLog) -and ((Get-Content -LiteralPath $serverLog -Raw) -match 'Use the extension to add folders')) { $ready = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "Helper startup timed out. Check $serverLog and $serverErrorLog" }
    & (Join-Path $PSScriptRoot 'install-extension.ps1') -Destination $extensionDirectory
    $env:VLC_PLUGIN_PATH = Join-Path $VlcDirectory 'plugins'
    $env:VLC_DATA_PATH = $VlcDirectory
    if ($PrepareOnly) {
        Write-Host "Portable preview prepared at $previewDirectory"
    } else {
        Write-Host 'In the new VLC window choose View > Share Library.'
        Write-Host 'Add a small media folder, then enable sharing.'
        Write-Host 'This preview stops its server when you close this VLC window.'
        $previewVlc = Start-Process -FilePath (Join-Path $previewDirectory 'vlc.exe') -ArgumentList '--ignore-config --no-one-instance --no-media-library --no-plugins-cache --no-metadata-network-access' -WorkingDirectory $previewDirectory -WindowStyle Normal -PassThru
        Wait-Process -Id $previewVlc.Id
    }
} finally {
    $env:VLC_PLUGIN_PATH = $oldPlugins
    $env:VLC_DATA_PATH = $oldData
    if ($helper -and -not $helper.HasExited) { Stop-Process -Id $helper.Id }
}
