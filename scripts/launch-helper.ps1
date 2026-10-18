param([int]$Port = 57642, [switch]$LocalOnly, [int]$OwnerPid = 0, [long]$OwnerStarted = 0)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDirectory = Join-Path $projectRoot 'build'
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$runtimePath = Join-Path $projectRoot 'runtime.json'
$runtime = if (Test-Path -LiteralPath $runtimePath) { Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json } else { $null }
$owner = $null
if ($OwnerPid -gt 0) {
    $owner = Get-Process -Id $OwnerPid -ErrorAction Stop
} else {
    # VLC's os.execute inserts cmd.exe/PowerShell between VLC and this script.
    # Trace those ancestors; never adopt an unrelated VLC by process-name search.
    if (-not ('LibraryShareBootstrap.Parents' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace LibraryShareBootstrap {
 public static class Parents {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  private struct Entry {
   public uint Size, Usage, Pid;
   public UIntPtr Heap;
   public uint Module, Threads, Parent;
   public int Priority;
   public uint Flags;
   [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string Name;
  }
  [DllImport("kernel32.dll", SetLastError=true)] private static extern IntPtr CreateToolhelp32Snapshot(uint flags,uint pid);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] private static extern bool Process32FirstW(IntPtr snapshot,ref Entry entry);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] private static extern bool Process32NextW(IntPtr snapshot,ref Entry entry);
  [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
  public static int Parent(int pid) {
   var snapshot=CreateToolhelp32Snapshot(2,0);
   if(snapshot==new IntPtr(-1)) return 0;
   try {
    var entry=new Entry(); entry.Size=(uint)Marshal.SizeOf(typeof(Entry));
    if(Process32FirstW(snapshot,ref entry)) do {
     if(entry.Pid==(uint)pid) return (int)entry.Parent;
    } while(Process32NextW(snapshot,ref entry));
    return 0;
   } finally { CloseHandle(snapshot); }
  }
 }
}
'@
    }
    $ancestorPid = $PID
    $childStarted = (Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks
    for ($depth = 0; $depth -lt 16; $depth++) {
        $ancestorPid = [LibraryShareBootstrap.Parents]::Parent($ancestorPid)
        if ($ancestorPid -le 0) { break }
        try { $ancestor = Get-Process -Id $ancestorPid -ErrorAction Stop } catch { break }
        $created = $ancestor.StartTime.ToUniversalTime().Ticks
        if ($created -gt $childStarted) { break }
        $childStarted = $created
        if ($ancestor.ProcessName -eq 'vlc') { $owner = $ancestor; break }
    }
}
if ($owner) {
    if ($owner.ProcessName -ne 'vlc' -or ($runtime -and $owner.Path -ne (Join-Path $runtime.VlcDirectory 'vlc.exe'))) {
        throw 'The helper must be started by this VLC installation.'
    }
    $created = $owner.StartTime.ToUniversalTime().Ticks
    if ($OwnerStarted -gt 0 -and $OwnerStarted -ne $created) { throw 'The original VLC process has already closed.' }
    $OwnerPid = $owner.Id
    $OwnerStarted = $created
} elseif ($runtime) {
    throw 'Open VLC and choose View > Share Library to start its helper.'
}
$tokenPath = Join-Path $dataDirectory 'library.json.control-token'
function Test-Helper {
    if (-not (Test-Path -LiteralPath $tokenPath)) { return $false }
    try {
        $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/local?token=$token&action=status" -TimeoutSec 1
        return $response.StatusCode -eq 200 -and $response.Content.Contains('<library>')
    } catch { return $false }
}
if (Test-Helper) {
    if ($owner) {
        $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        $attached = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/local?token=$token&action=attach-owner&pid=$OwnerPid&created=$OwnerStarted" -TimeoutSec 2
        if ($attached.Content.Contains('<error>')) { throw 'Could not attach the helper to VLC. Close VLC and rerun the installer.' }
    }
    return
}
$dotnet = if ($runtime) { $runtime.Dotnet } else { (Get-Command dotnet).Source }
$server = if ($runtime) { Join-Path $projectRoot 'server\LibraryShare.Server.dll' } else { Join-Path $projectRoot 'build\server\LibraryShare.Server.dll' }
if (-not (Test-Path -LiteralPath $server)) { throw 'Build or install Library Share first.' }
if ($runtime) {
    $env:VLC_DIR = $runtime.VlcDirectory
}
$listen = if ($LocalOnly) { '127.0.0.1' } else { '0.0.0.0' }
$hostExecutable = [IO.Path]::ChangeExtension($server, '.exe')
$serverArgs = @('--project', $projectRoot, '--listen', $listen, '--port', $Port.ToString())
if (-not (Test-Path -LiteralPath $hostExecutable)) { $hostExecutable = $dotnet; $serverArgs = @($server) + $serverArgs }
if ($runtime) { $env:DOTNET_ROOT = Split-Path -Parent $runtime.Dotnet }
if ($runtime) { $serverArgs += @('--extension-dir', $runtime.ExtensionDirectory) }
if ($owner) { $serverArgs += @('--owner-pid', $OwnerPid.ToString(), '--owner-started', $OwnerStarted.ToString()) }
$quoted = ($serverArgs | ForEach-Object { '"{0}"' -f $_ }) -join ' '
$process = Start-Process -FilePath $hostExecutable -ArgumentList $quoted -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataDirectory 'helper.log') -RedirectStandardError (Join-Path $dataDirectory 'helper-error.log')
Set-Content -LiteralPath (Join-Path $dataDirectory 'helper.pid') -Value $process.Id
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    if ($process.HasExited) { throw 'Helper could not start. Check build\helper-error.log; close another running preview first.' }
    if (Test-Helper) { return }
    Start-Sleep -Milliseconds 150
}
throw 'Helper startup took longer than expected. Click Refresh status in VLC.'
