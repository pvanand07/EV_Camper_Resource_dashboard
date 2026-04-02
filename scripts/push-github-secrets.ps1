<#
.SYNOPSIS
  Push repository secrets to GitHub using the gh CLI.

  Two modes:
  - -EnvFile <path>  → gh secret set -f (dotenv file; supports multiline values per gh)
  - -FromEnvironment → reads each known secret from process/user/machine environment

  Requires: gh auth login, and repo scope for secrets.

  Typical keys (see .github/workflows/deploy.yml): CORS_ORIGINS, OPENROUTER_KEY,
  ANALYTICS_ADMIN_KEY, VPS_HOST, VPS_USER, VPS_SSH_KEY, GH_PAT
#>
[CmdletBinding()]
param(
    [string] $EnvFile = '',

    [switch] $FromEnvironment,

    [string[]] $SecretNames = @(
        'CORS_ORIGINS',
        'OPENROUTER_KEY',
        'ANALYTICS_ADMIN_KEY',
        'VPS_HOST',
        'VPS_USER',
        'VPS_SSH_KEY',
        'GH_PAT'
    ),

    [string] $Repo = ''
)

$ErrorActionPreference = 'Stop'

if ($FromEnvironment -and -not [string]::IsNullOrWhiteSpace($EnvFile)) {
    Write-Error 'Use either -EnvFile or -FromEnvironment, not both.'
}

if (-not $FromEnvironment -and [string]::IsNullOrWhiteSpace($EnvFile)) {
    Write-Error @'
Specify -EnvFile path or -FromEnvironment.

Examples:
  .\scripts\push-github-secrets.ps1 -EnvFile .\.env.secrets
  .\scripts\push-github-secrets.ps1 -FromEnvironment
  .\scripts\push-github-secrets.ps1 -EnvFile .\.env.secrets -Repo owner/repo
'@
}

function Get-GhArgs {
    if ([string]::IsNullOrWhiteSpace($Repo)) { return @() }
    return @('-R', $Repo)
}

$null = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error 'gh is not authenticated. Run: gh auth login'
}

$ghExtra = Get-GhArgs

if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
    $resolved = Resolve-Path -Path $EnvFile -ErrorAction Stop
    & gh secret set -f $resolved.Path @ghExtra
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Secrets synced from $($resolved.Path)"
    exit 0
}

foreach ($name in $SecretNames) {
    $v = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrEmpty($v)) {
        $v = [Environment]::GetEnvironmentVariable($name, 'User')
    }
    if ([string]::IsNullOrEmpty($v)) {
        $v = [Environment]::GetEnvironmentVariable($name, 'Machine')
    }
    if ([string]::IsNullOrEmpty($v)) {
        Write-Warning "Skipping $name (not set in environment)"
        continue
    }
    $v | & gh secret set $name @ghExtra
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Set $name"
}

Write-Host 'Done.'
