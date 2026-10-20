$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'package.ps1')
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework C# compiler is missing.' }
$dist = Join-Path $root 'build\dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$zip = Join-Path $dist 'LibraryShare-payload.zip'
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
# Build the distributable from an explicit allowlist, never from development data/configuration.
$stage = Join-Path $root ('build\installer-payload-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $stage 'server'),(Join-Path $stage 'scripts'),(Join-Path $stage 'vlc') -Force | Out-Null
foreach ($file in @('LibraryShare.Server.exe','LibraryShare.Server.dll','LibraryShare.Server.deps.json','LibraryShare.Server.runtimeconfig.json')) {
    Copy-Item -LiteralPath (Join-Path $root "build\package\server\$file") -Destination (Join-Path $stage 'server')
}
foreach ($file in @('launch-helper.ps1','pick-path.ps1','import-icon.ps1','configure-firewall.ps1','firewall-rules.ps1',
    'check-prerequisites.ps1','install-vlc-plugin.ps1','launch-share.ps1','register-application.ps1','uninstall.ps1')) {
    Copy-Item -LiteralPath (Join-Path $root "build\package\scripts\$file") -Destination (Join-Path $stage 'scripts')
}
Copy-Item -LiteralPath (Join-Path $root 'build\package\vlc\library_share.lua') -Destination (Join-Path $stage 'vlc')
[IO.Compression.ZipFile]::CreateFromDirectory($stage,$zip,[IO.Compression.CompressionLevel]::Optimal,$false)
$installer = Join-Path $dist 'LibraryShare-0.3.0-alpha.2-Setup.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$installer" "/win32manifest:$(Join-Path $root 'src\LibraryShare.Setup\setup.manifest')" "/resource:$zip,LibraryShare.Payload.zip" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll (Join-Path $root 'src\LibraryShare.Setup\Setup.cs')
if ($LASTEXITCODE -ne 0) { throw 'Setup compilation failed.' }
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
"$hash  $([IO.Path]::GetFileName($installer))" | Set-Content -LiteralPath ($installer + '.sha256') -Encoding ASCII
Write-Host "Built $installer"
Write-Host 'Alpha requirements: installed VLC 3.x x64 and .NET 8 ASP.NET Core Runtime x64. Python is not required.'
Write-Host 'No new build tools downloaded. Uses Windows C# compiler plus the installed .NET SDK.'
