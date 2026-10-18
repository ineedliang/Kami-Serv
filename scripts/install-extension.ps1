param([string]$Destination = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$staged = Join-Path $projectRoot 'build\vlc-extension'
if (-not (Test-Path -LiteralPath (Join-Path $staged 'modules\library_share_config.lua'))) {
    throw 'Start start-share.cmd first so the helper can stage its connection settings.'
}
if (-not $Destination) { $Destination = Join-Path $env:APPDATA 'vlc\lua\extensions' }
$moduleDirectory = Join-Path $Destination 'modules'
New-Item -ItemType Directory -Path $Destination,$moduleDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $staged 'library_share.lua') -Destination (Join-Path $Destination 'library_share.lua') -Force
Copy-Item -LiteralPath (Join-Path $staged 'modules\library_share_config.lua') -Destination (Join-Path $moduleDirectory 'library_share_config.lua') -Force
Write-Host "Extension installed in $Destination"
Write-Host 'Reopen VLC, then choose View > Share Library.'
