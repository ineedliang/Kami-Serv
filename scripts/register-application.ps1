param([Parameter(Mandatory=$true)][string]$InstallDirectory, [switch]$DesktopShortcut, [switch]$SkipRegistration)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
$runtime = Get-Content -LiteralPath (Join-Path $root 'runtime.json') -Raw | ConvertFrom-Json
$files = @('runtime.json','vlc\library_share.lua')
foreach ($file in @('LibraryShare.Server.exe','LibraryShare.Server.dll','LibraryShare.Server.deps.json','LibraryShare.Server.runtimeconfig.json','LibraryShare.Server.pdb')) {
    if (Test-Path -LiteralPath (Join-Path $root "server\$file")) { $files += "server\$file" }
}
foreach ($file in @('launch-helper.ps1','pick-path.ps1','import-icon.ps1','configure-firewall.ps1','firewall-rules.ps1',
    'check-prerequisites.ps1','install-vlc-plugin.ps1','launch-share.ps1','register-application.ps1','uninstall.ps1')) {
    $files += "scripts\$file"
}
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Library Share'
$desktop = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Library Share.lnk'
@{ Product='LibraryShare'; Version='0.3.0-alpha.2'; Root=$root; ExtensionDirectory=$runtime.ExtensionDirectory; Files=$files;
    Registered=(-not $SkipRegistration); DesktopShortcut=[bool]$DesktopShortcut } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $root 'installed-files.json') -Encoding UTF8
if ($SkipRegistration) { return }
$powershell = Join-Path $PSHOME 'powershell.exe'
$shell = New-Object -ComObject WScript.Shell
New-Item -ItemType Directory -Path $menu -Force | Out-Null
$shortcutPaths = @(Join-Path $menu 'Library Share.lnk')
if ($DesktopShortcut) { $shortcutPaths += $desktop }
foreach ($path in $shortcutPaths) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = '-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $root 'scripts\launch-share.ps1') + '"'
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = (Join-Path $runtime.VlcDirectory 'vlc.exe') + ',0'
    $shortcut.Description = 'Open VLC with Library Share. In VLC choose View > Share Library.'
    $shortcut.Save()
}
$key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\LibraryShare')
try {
    $key.SetValue('DisplayName','Library Share for VLC (alpha)')
    $key.SetValue('DisplayVersion','0.3.0-alpha.2')
    $key.SetValue('Publisher','Library Share Project')
    $key.SetValue('InstallLocation',$root)
    $key.SetValue('DisplayIcon',(Join-Path $runtime.VlcDirectory 'vlc.exe'))
    $key.SetValue('UninstallString','"' + $powershell + '" -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $root 'scripts\uninstall.ps1') + '"')
    $key.SetValue('NoModify',1,[Microsoft.Win32.RegistryValueKind]::DWord)
    $key.SetValue('NoRepair',1,[Microsoft.Win32.RegistryValueKind]::DWord)
    $key.SetValue('InstallDate',(Get-Date -Format yyyyMMdd))
} finally { $key.Dispose() }
