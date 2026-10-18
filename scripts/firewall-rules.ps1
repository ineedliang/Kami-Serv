# Shared by the setup/repair command and its tests. Loading this file changes nothing.
function Get-LibraryShareFirewallPlan {
    param([string]$InstallDirectory, [string]$ProgramPath, [ValidateRange(1,65535)][int]$Port = 57642)
    $root = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
    $program = [IO.Path]::GetFullPath($ProgramPath)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToUpperInvariant())))).Replace('-','').Substring(0,16) }
    finally { $sha.Dispose() }
    foreach ($item in @(@('HTTP',6,$Port), @('Discovery',17,1900))) {
        [pscustomobject]@{ Name = "LibraryShare.$hash.$($item[0])"; DisplayName = "Library Share - $($item[0])";
            Group = "Library Share ($hash)"; Program = $program; Protocol = [int]$item[1]; LocalPorts = [string]$item[2];
            Profiles = 2; Direction = 1; Action = 1; RemoteAddresses = 'LocalSubnet'; EdgeTraversal = $false; Enabled = $true }
    }
}
function Get-LibraryShareFirewallPolicy { New-Object -ComObject HNetCfg.FwPolicy2 }
function New-LibraryShareFirewallRule { New-Object -ComObject HNetCfg.FWRule }
function Find-LibraryShareFirewallRule {
    param($Policy, [string]$Name)
    try { $Policy.Rules.Item($Name) } catch [System.IO.FileNotFoundException] { $null }
    catch [System.Runtime.InteropServices.COMException] {
        if ($_.Exception.HResult -ne -2147024894) { throw }
        $null
    }
}
function Test-LibraryShareFirewallRule {
    param($Rule, $Plan)
    if ($null -eq $Rule) { return $false }
    return $Rule.Grouping -eq $Plan.Group -and $Rule.ApplicationName -eq $Plan.Program -and
        $Rule.Protocol -eq $Plan.Protocol -and $Rule.LocalPorts -eq $Plan.LocalPorts -and
        $Rule.Profiles -eq 2 -and $Rule.Direction -eq 1 -and $Rule.Action -eq 1 -and
        $Rule.RemoteAddresses -eq 'LocalSubnet' -and $Rule.Enabled -and -not $Rule.EdgeTraversal -and
        $Rule.LocalAddresses -eq '*' -and $Rule.RemotePorts -eq '*' -and $Rule.InterfaceTypes -eq 'All' -and
        [string]::IsNullOrEmpty($Rule.ServiceName)
}
function Get-LibraryShareFirewallStatus {
    param($Policy, $Plan)
    $configured = $true
    $owned = 0
    foreach ($item in $Plan) {
        $rule = Find-LibraryShareFirewallRule $Policy $item.Name
        if ($null -ne $rule -and $rule.Grouping -eq $item.Group) { $owned++ }
        if (-not (Test-LibraryShareFirewallRule $rule $item)) { $configured = $false }
    }
    $active = [int]$Policy.CurrentProfileTypes
    $privateActive = ($active -band 2) -ne 0
    $privateEnabled = [bool]$Policy.FirewallEnabled(2)
    $message = if ($configured) { 'Windows Firewall rules verified: Private networks, local subnet only.' }
        else { 'Windows Firewall access is not configured. Use Allow / repair firewall access.' }
    if (-not $privateActive) { $message += ' No active Private network. Mark your trusted home network Private in Windows Settings.' }
    if (-not $privateEnabled) { $message += ' Windows Firewall is disabled for Private networks; rules cannot confirm protection.' }
    if ([int]$Policy.LocalPolicyModifyState -ne 0) { $message += ' Managed Windows policy restricts local firewall rules; contact your administrator.' }
    [pscustomobject]@{ State = $(if ($configured) {'configured'} else {'not-configured'}); Message = $message;
        PrivateActive = $privateActive; PrivateFirewallEnabled = $privateEnabled; OwnedRules = $owned }
}
function Set-LibraryShareFirewallRules {
    param($Policy, $Plan, [ValidateSet('Allow','Remove')][string]$Action)
    # Check ownership of every name before changing anything. Other applications' rules are never removed.
    foreach ($item in $Plan) {
        $existing = Find-LibraryShareFirewallRule $Policy $item.Name
        if ($null -ne $existing -and $existing.Grouping -ne $item.Group) { throw "Firewall rule name is owned by another application: $($item.Name)" }
    }
    foreach ($item in $Plan) {
        $existing = Find-LibraryShareFirewallRule $Policy $item.Name
        if ($Action -eq 'Allow' -and (Test-LibraryShareFirewallRule $existing $item)) { continue }
        if ($null -ne $existing) { $Policy.Rules.Remove($item.Name) }
        if ($Action -eq 'Allow') {
            $rule = New-LibraryShareFirewallRule
            $rule.Name = $item.Name
            $rule.Description = 'Library Share media delivery/discovery on the local home network. Managed by Library Share setup.'
            $rule.Grouping = $item.Group
            $rule.ApplicationName = $item.Program
            $rule.Protocol = $item.Protocol
            $rule.LocalPorts = $item.LocalPorts
            $rule.RemotePorts = '*'
            $rule.LocalAddresses = '*'
            $rule.RemoteAddresses = $item.RemoteAddresses
            $rule.InterfaceTypes = 'All'
            $rule.Profiles = $item.Profiles
            $rule.Direction = $item.Direction
            $rule.Action = $item.Action
            $rule.EdgeTraversal = $item.EdgeTraversal
            $rule.Enabled = $item.Enabled
            $Policy.Rules.Add($rule)
        }
    }
    if ($Action -eq 'Allow') {
        foreach ($item in $Plan) {
            if (-not (Test-LibraryShareFirewallRule (Find-LibraryShareFirewallRule $Policy $item.Name) $item)) { throw 'Windows did not retain the requested firewall rules.' }
        }
    }
}
