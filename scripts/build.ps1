$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:DOTNET_CLI_HOME = Join-Path $projectRoot 'build\.dotnet'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH = 'false'
$env:NUGET_PACKAGES = Join-Path $projectRoot 'build\.nuget'
Push-Location $projectRoot
try {
    & dotnet build 'src\LibraryShare.Server\LibraryShare.Server.csproj' --configuration Release --output 'build\server' --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Library Share build failed.' }
} finally { Pop-Location }
