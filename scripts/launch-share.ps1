$ErrorActionPreference = 'Stop'
try {
    $root = Split-Path -Parent $PSScriptRoot
    $runtime = Get-Content -LiteralPath (Join-Path $root 'runtime.json') -Raw | ConvertFrom-Json
    $vlc = Start-Process -FilePath (Join-Path $runtime.VlcDirectory 'vlc.exe') -ArgumentList '--no-one-instance' -WindowStyle Normal -PassThru
    & (Join-Path $PSScriptRoot 'launch-helper.ps1') -OwnerPid $vlc.Id -OwnerStarted ($vlc.StartTime.ToUniversalTime().Ticks)
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Library Share could not start', 'OK', 'Error') | Out-Null
    exit 1
}
