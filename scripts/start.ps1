param(
    [string]$Address = '',
    [switch]$LocalOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'build.ps1')
$server = Join-Path $projectRoot 'build\server\LibraryShare.Server.dll'
$listen = if ($LocalOnly) { '127.0.0.1' } else { '0.0.0.0' }
$serverArgs = @($server, '--project', $projectRoot, '--listen', $listen)
if ($Address) { $serverArgs += @('--advertise', $Address) }
Write-Host 'Keep this window open while sharing. Press Ctrl+C to stop.'
& dotnet @serverArgs
exit $LASTEXITCODE
