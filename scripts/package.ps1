$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$package = Join-Path $projectRoot 'build\package'
$env:DOTNET_CLI_HOME = Join-Path $projectRoot 'build\.dotnet'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:NUGET_PACKAGES = Join-Path $projectRoot 'build\.nuget'
Push-Location $projectRoot
try {
    & dotnet build 'src\LibraryShare.Server\LibraryShare.Server.csproj' --configuration Release --output (Join-Path $package 'server') --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    New-Item -ItemType Directory -Path (Join-Path $package 'vlc'),(Join-Path $package 'scripts') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'vlc\library_share.lua') -Destination (Join-Path $package 'vlc') -Force
    foreach ($name in @('launch-helper.ps1','pick-path.ps1','import-icon.ps1','configure-firewall.ps1','firewall-rules.ps1',
        'check-prerequisites.ps1','install-vlc-plugin.ps1','launch-share.ps1','register-application.ps1','uninstall.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $package 'scripts') -Force
    }
    $legacyWorker = Join-Path $package 'scripts\probe-vlc-remux.py'
    if (Test-Path -LiteralPath $legacyWorker) { Remove-Item -LiteralPath $legacyWorker }
    Write-Host "Prepared plugin and helper in $package"
} finally { Pop-Location }
