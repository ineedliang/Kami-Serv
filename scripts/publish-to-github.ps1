param([string]$Repository = 'https://github.com/ineedliang/Kami-Serv.git')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$git = (Get-Command git.exe -ErrorAction Stop).Source
function Invoke-Git {
    param([string[]]$Arguments)
    & $git @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git command failed: $($Arguments[0]). Check the message above. No force push is performed." }
}
function Assert-PublishPaths {
    param([string[]]$Files, [string[]]$ProjectPaths)
    foreach ($path in $Files) {
        $inProject = $false
        foreach ($allowed in $ProjectPaths) {
            if ($path -ceq $allowed -or ($allowed -cin @('docs','scripts','src','tests','vlc') -and $path.StartsWith($allowed + '/', [StringComparison]::Ordinal))) {
                $inProject = $true
                break
            }
        }
        if (-not $inProject) { throw "Unrelated file is already staged: $path. Review or unstage it before publishing. No commit or push was performed." }
        if ($path -match '(^|/)(build|bin|obj|__pycache__|\.git)/|\.(mp4|avi|mkv|mov|m4v|srt|ass|ssa|sub|idx|vtt|mp3|flac|wav|log|pid|exe|zip)$|control-token|(^|/)(runtime\.json|library\.json[^/]*|library_share_config\.lua|\.env[^/]*)$') {
            throw "Unexpected private/generated/media file is staged: $path. Review or unstage it before publishing. No commit or push was performed."
        }
    }
}
Push-Location $root
try {
    # This script runs on the user's PC. It does not change network/proxy settings
    # or request access tokens. Git's normal credential manager handles sign-in.
    if (-not (Test-Path -LiteralPath (Join-Path $root '.git'))) { Invoke-Git -Arguments @('init','-b','main') }
    $remote = & $git config --get remote.origin.url
    if ($LASTEXITCODE -ne 0) { Invoke-Git -Arguments @('remote','add','origin',$Repository) }
    elseif ($remote.Trim() -ne $Repository) { throw "The existing origin is $remote. Review it before publishing; it was not changed." }

    # Re-running after a failed check must accept this project's already-staged
    # files, then restage their corrected working copies before validation.
    $paths = @('.gitattributes','.gitignore','NuGet.Config','README.md','global.json',
        'build-installer.cmd','install-vlc-plugin.cmd','preview-share.cmd','start-share.cmd',
        'publish-to-github.cmd','docs','scripts','src','tests','vlc')
    $existingStage = @(& $git -c core.quotepath=false diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the Git index.' }
    Assert-PublishPaths -Files $existingStage -ProjectPaths $paths
    Invoke-Git -Arguments @('fetch','origin')
    $hasHead = $false
    & $git rev-parse --verify --quiet HEAD | Out-Null
    if ($LASTEXITCODE -eq 0) { $hasHead = $true }
    $remoteMain = $null
    foreach ($candidate in @('main','master')) {
        & $git show-ref --verify --quiet "refs/remotes/origin/$candidate"
        if ($LASTEXITCODE -eq 0) { $remoteMain = $candidate; break }
    }
    $targetBranch = if ($remoteMain) { $remoteMain } else { 'main' }
    if ($hasHead) {
        $branch = (& $git branch --show-current).Trim()
        if ($branch -ne $targetBranch) { throw "Current branch is '$branch'; switch to '$targetBranch' before publishing." }
        if ($remoteMain) {
            & $git merge-base --is-ancestor "origin/$remoteMain" HEAD
            if ($LASTEXITCODE -ne 0) { throw "Remote history is not included in this branch. Review and merge origin/$remoteMain before publishing. No history was overwritten." }
        }
    } elseif ($remoteMain) {
        # Adopt existing remote history without overwriting the local source files.
        # This is used only in an unborn, empty-index repository.
        Invoke-Git -Arguments @('symbolic-ref','HEAD',"refs/heads/$targetBranch")
        Invoke-Git -Arguments @('update-ref',"refs/heads/$targetBranch", "refs/remotes/origin/$remoteMain")
        Invoke-Git -Arguments @('read-tree','HEAD')
    }

    # Explicit project-source roots only: no build output or root media fixtures.
    Invoke-Git -Arguments (@('add','--') + $paths)
    $staged = @(& $git -c core.quotepath=false diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) { throw 'Could not validate the staged file list.' }
    Assert-PublishPaths -Files $staged -ProjectPaths $paths
    Invoke-Git -Arguments @('diff','--cached','--check')
    & $git diff --cached --quiet
    if ($LASTEXITCODE -eq 1) {
        $name = & $git config user.name
        $email = & $git config user.email
        $identity = @()
        if (-not $name) { $identity += @('-c','user.name=Kami-Serv Project') }
        if (-not $email) { $identity += @('-c','user.email=kami-serv@localhost') }
        Invoke-Git -Arguments ($identity + @('commit','-m','Add Kami-Serv Windows alpha, installer, tests and documentation'))
    } elseif ($LASTEXITCODE -ne 0) { throw 'Could not inspect staged changes.' }
    Invoke-Git -Arguments @('push','-u','origin',$targetBranch)
    $local = (& $git rev-parse HEAD).Trim()
    $remoteHead = @(& $git ls-remote origin "refs/heads/$targetBranch")
    if ($LASTEXITCODE -ne 0 -or $remoteHead.Count -ne 1 -or ($remoteHead[0] -split '\s+')[0] -ne $local) {
        throw 'Push returned, but verification of the GitHub branch did not succeed. Check the repository before retrying.'
    }
    Write-Host "Published and verified: $Repository ($targetBranch at $local)"
    Write-Host 'Installer binaries remain in build\dist. This command publishes the source and documentation only.'
} finally { Pop-Location }
