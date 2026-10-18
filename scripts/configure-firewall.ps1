param(
    [ValidateSet('Status','Allow','Remove','Plan')][string]$Action = 'Status',
    [string]$ProgramPath,
    [ValidateRange(1,65535)][int]$Port = 57642,
    [switch]$Elevated
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'firewall-rules.ps1')
if (-not $ProgramPath) {
    $ProgramPath = Join-Path $root 'server\LibraryShare.Server.exe'
    if (-not (Test-Path -LiteralPath $ProgramPath)) { $ProgramPath = Join-Path $root 'build\server\LibraryShare.Server.exe' }
}
$plan = @(Get-LibraryShareFirewallPlan $root $ProgramPath $Port)
if ($Action -eq 'Plan') { ConvertTo-Json -InputObject $plan -Compress; return }
try {
    if ($Action -in @('Allow','Remove')) {
        if (-not (Test-Path -LiteralPath $ProgramPath -PathType Leaf)) { throw 'Library Share helper executable is missing. Reinstall Library Share first.' }
        if (-not $Elevated) {
            # Encode paths as data, never interpolate a user path into PowerShell source.
            $data = @{ Script = $PSCommandPath; Action = $Action; Program = $ProgramPath; Port = $Port } | ConvertTo-Json -Compress
            $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($data))
            $code = '$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(''' + $encoded + '''))|ConvertFrom-Json; & $p.Script -Action $p.Action -ProgramPath $p.Program -Port $p.Port -Elevated'
            $arguments = '-NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
            try { $child = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -PassThru -Wait }
            catch {
                $errorObject = $_.Exception
                while ($errorObject.InnerException) { $errorObject = $errorObject.InnerException }
                if ($errorObject -is [ComponentModel.Win32Exception] -and $errorObject.NativeErrorCode -eq 1223) {
                    @{ State='cancelled'; Message='Firewall permission cancelled. No firewall setup was performed.' } | ConvertTo-Json -Compress
                    return
                }
                throw
            }
            if ($child.ExitCode -ne 0) { throw 'Windows could not update the firewall rules. Check administrator permission or managed firewall policy.' }
        } else {
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = New-Object Security.Principal.WindowsPrincipal($identity)
            if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator permission is required to change firewall rules.' }
            Set-LibraryShareFirewallRules (Get-LibraryShareFirewallPolicy) $plan $Action
            exit 0
        }
    }
    $policy = Get-LibraryShareFirewallPolicy
    if ($Action -eq 'Remove') {
        foreach ($item in $plan) { if ($null -ne (Find-LibraryShareFirewallRule $policy $item.Name)) { throw 'Windows did not remove the Library Share firewall rules.' } }
        @{State='removed'; Message='Library Share firewall rules removed.'} | ConvertTo-Json -Compress
    } else { Get-LibraryShareFirewallStatus $policy $plan | ConvertTo-Json -Compress }
} catch {
    if ($Elevated) { exit 1 }
    @{State='failed'; Message=('Firewall setup/check failed: ' + $_.Exception.Message)} | ConvertTo-Json -Compress
    exit 1
}
