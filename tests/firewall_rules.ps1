# Tests the real rule logic against an in-memory policy. Never touches Windows Firewall.
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\firewall-rules.ps1')
class FakeRules {
    [hashtable]$Items = @{}
    [int]$Adds = 0
    [int]$Removes = 0
    [object] Item([string]$name) { return $this.Items[$name] }
    [void] Add($rule) { $this.Items[$rule.Name] = $rule; $this.Adds++ }
    [void] Remove([string]$name) { $this.Items.Remove($name); $this.Removes++ }
}
class FakePolicy {
    [FakeRules]$Rules = [FakeRules]::new()
    [int]$CurrentProfileTypes = 2
    [bool] FirewallEnabled([int]$profile) { return $true }
}
function New-LibraryShareFirewallRule {
    [pscustomobject]@{ Name=''; Description=''; Grouping=''; ApplicationName=''; Protocol=0; LocalPorts=''; RemotePorts='';
        LocalAddresses=''; RemoteAddresses=''; InterfaceTypes=''; Profiles=0; Direction=0; Action=0; EdgeTraversal=$true; Enabled=$false; ServiceName='' }
}
function Assert($value, [string]$message) { if (-not $value) { throw $message } }
$plan = @(Get-LibraryShareFirewallPlan 'C:\Test app & cafe' 'C:\Test app & cafe\server\LibraryShare.Server.exe')
Assert ($plan.Count -eq 2) 'Expected exactly HTTP and discovery rules'
Assert ($plan[0].Protocol -eq 6 -and $plan[0].LocalPorts -eq '57642') 'Wrong HTTP port'
Assert ($plan[1].Protocol -eq 17 -and $plan[1].LocalPorts -eq '1900') 'Wrong discovery port'
$policy = [FakePolicy]::new()
Assert ((Get-LibraryShareFirewallStatus $policy $plan).State -eq 'not-configured') 'Fresh rules reported configured'
Set-LibraryShareFirewallRules $policy $plan Allow
Assert ((Get-LibraryShareFirewallStatus $policy $plan).State -eq 'configured') 'Added rules not verified'
Set-LibraryShareFirewallRules $policy $plan Allow
Assert ($policy.Rules.Adds -eq 2 -and $policy.Rules.Removes -eq 0) 'Repeated setup created duplicates'
$policy.Rules.Items[$plan[0].Name].Profiles = 7
$policy.Rules.Items[$plan[0].Name].RemoteAddresses = '*'
Assert ((Get-LibraryShareFirewallStatus $policy $plan).State -eq 'not-configured') 'Overbroad rule accepted'
Set-LibraryShareFirewallRules $policy $plan Allow
Assert ($policy.Rules.Adds -eq 3 -and $policy.Rules.Removes -eq 1) 'Repair failed'
Assert ((Get-LibraryShareFirewallStatus $policy $plan).State -eq 'configured') 'Repaired rule failed verification'
$policy.CurrentProfileTypes = 4
Assert ((Get-LibraryShareFirewallStatus $policy $plan).Message.Contains('No active Private network')) 'Public profile not explained'
$otherPlan = @(Get-LibraryShareFirewallPlan 'C:\Another user\LibraryShare' 'C:\Another user\LibraryShare\server\LibraryShare.Server.exe')
Assert ($otherPlan[0].Name -ne $plan[0].Name) 'Installations collide'
$policy.Rules.Items[$otherPlan[0].Name] = [pscustomobject]@{ Name=$otherPlan[0].Name; Grouping='Unrelated application' }
$adds = $policy.Rules.Adds; $removes = $policy.Rules.Removes
$rejected = $false
try { Set-LibraryShareFirewallRules $policy $otherPlan Allow } catch { $rejected = $true }
Assert $rejected 'Foreign rule collision not rejected'
Assert ($policy.Rules.Adds -eq $adds -and $policy.Rules.Removes -eq $removes) 'Collision changed rules'
Set-LibraryShareFirewallRules $policy $plan Remove
Assert ($policy.Rules.Items.Count -eq 1 -and $policy.Rules.Items.ContainsKey($otherPlan[0].Name)) 'Uninstall removed another application rule'
Set-LibraryShareFirewallRules $policy $plan Remove
Assert ($policy.Rules.Items.Count -eq 1) 'Repeated uninstall not idempotent'
Write-Host 'PASS: scoped rules, duplicate prevention, verification/repair, Public-network advice, ownership, uninstall (in-memory firewall only)'
