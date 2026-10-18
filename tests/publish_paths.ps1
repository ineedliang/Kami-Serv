# Test the publisher's actual path validation without staging, committing, or network access.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts\publish-to-github.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Publish script has syntax errors.' }
$function = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-PublishPaths' }, $true)
if (-not $function) { throw 'Publisher path validation is missing.' }
. ([scriptblock]::Create($function.Extent.Text))
$paths = @('.gitattributes','.gitignore','NuGet.Config','README.md','global.json',
    'build-installer.cmd','install-vlc-plugin.cmd','preview-share.cmd','start-share.cmd',
    'publish-to-github.cmd','docs','scripts','src','tests','vlc')
Assert-PublishPaths -Files @() -ProjectPaths $paths
Assert-PublishPaths -Files @('README.md','.gitignore','scripts/build.ps1','src/LibraryShare.Server/Program.cs','docs/how-it-works.md','vlc/library_share.lua','tests/integration.py') -ProjectPaths $paths
foreach ($invalid in @('notes.txt','build/library.json','scripts/runtime.json','src/LibraryShare.Server/obj/project.assets.json',
    'docs/password.control-token','tests/clip.mp4','tests/captions.srt','tests/__pycache__/file.pyc','vlc/library_share_config.lua','scripts/.env','src/application.exe')) {
    $rejected = $false
    try { Assert-PublishPaths -Files @('README.md',$invalid) -ProjectPaths $paths } catch { $rejected = $true }
    if (-not $rejected) { throw "Publisher accepted an unexpected staged file: $invalid" }
}
Write-Host 'PASS: publisher accepts previously staged project files and rejects unrelated, private, generated, and media files.'
