param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
if (-not $Quiet) { Add-Type -AssemblyName System.Windows.Forms }
try {
    $root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
    $manifest = Get-Content -LiteralPath (Join-Path $root 'installed-files.json') -Raw | ConvertFrom-Json
    if ($manifest.Product -ne 'LibraryShare' -or $manifest.Root -ne $root) { throw 'Installation manifest does not match this application.' }
    # Resolve every owned path before deleting any file. Media/data is never an uninstall target.
    $targets = foreach ($file in $manifest.Files) {
        $path = [IO.Path]::GetFullPath((Join-Path $root $file))
        if (-not $path.StartsWith($root + '\',[StringComparison]::OrdinalIgnoreCase) -or
            ($file -ne 'runtime.json' -and $file -notmatch '^(server|scripts|vlc)\\')) { throw 'Invalid path in installation manifest.' }
        $relative = $path.Substring($root.Length + 1)
        if ($relative -ne 'runtime.json' -and $relative -notmatch '^(server|scripts|vlc)\\') { throw 'Invalid resolved uninstall path.' }
        $part = $path
        while ($part.Length -ge $root.Length) {
            if ((Test-Path -LiteralPath $part) -and ((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Uninstall will not follow a junction or symbolic link.' }
            $part = Split-Path -Parent $part
        }
        $path
    }
    if (-not $Quiet -and [Windows.Forms.MessageBox]::Show('Remove Library Share, its VLC extension, shortcuts and firewall rules? Your saved settings and prepared videos will be kept.','Uninstall Library Share','YesNo','Question','Button2') -ne 'Yes') { return }
    $firewall = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'configure-firewall.ps1') -Action Status | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $firewall.State -eq 'failed') { throw 'Could not check the firewall rules. Uninstall stopped before removing application files.' }
    if ($firewall.OwnedRules -gt 0) {
        $removed = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'configure-firewall.ps1') -Action Remove | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $removed.State -ne 'removed') { throw 'Firewall removal did not finish. Uninstall stopped; retry and approve the Windows permission prompt.' }
    }
    $tokenPath = Join-Path $root 'build\library.json.control-token'
    if (Test-Path -LiteralPath $tokenPath) {
        $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:57642/local?token=$token&action=shutdown" -TimeoutSec 3 | Out-Null
            $pidFile = Join-Path $root 'build\helper.pid'
            if (Test-Path -LiteralPath $pidFile) {
                $helperPid = [int](Get-Content -LiteralPath $pidFile -Raw)
                $helper = Get-Process -Id $helperPid -ErrorAction SilentlyContinue
                if ($helper -and $helper.Path -eq (Join-Path $root 'server\LibraryShare.Server.exe')) {
                    if (-not $helper.WaitForExit(8000)) { throw 'Helper is still stopping. Close VLC and retry uninstall.' }
                }
            }
            Start-Sleep -Milliseconds 300
        } catch { }
    }
    # Extension files are restricted to the two filenames installed by this app.
    $extension = [IO.Path]::GetFullPath($manifest.ExtensionDirectory)
    foreach ($file in @('library_share.lua','modules\library_share_config.lua')) {
        $path = Join-Path $extension $file
        if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
    }
    foreach ($path in $targets) { if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force } }
    if ($manifest.Registered) {
        $menuShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Library Share\Library Share.lnk'
        $desktopShortcut = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Library Share.lnk'
        if (Test-Path -LiteralPath $menuShortcut) { Remove-Item -LiteralPath $menuShortcut -Force }
        if ($manifest.DesktopShortcut -and (Test-Path -LiteralPath $desktopShortcut)) { Remove-Item -LiteralPath $desktopShortcut -Force }
        [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree('Software\Microsoft\Windows\CurrentVersion\Uninstall\LibraryShare',$false)
    }
    Remove-Item -LiteralPath (Join-Path $root 'installed-files.json') -Force
    # Empty program directories may remain; there is deliberately no recursive deletion of the installation/data directory.
    if (-not $Quiet) { [Windows.Forms.MessageBox]::Show("Library Share removed. Settings and prepared videos remain in $root\build.",'Library Share','OK','Information') | Out-Null }
} catch {
    if ($Quiet) { throw }
    [Windows.Forms.MessageBox]::Show($_.Exception.Message,'Uninstall could not finish','OK','Error') | Out-Null
    exit 1
}
