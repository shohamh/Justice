#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$E2eDatabaseUrl,
    [string]$E2eAdminDatabaseUrl,
    [switch]$ValidateOnly,
    [switch]$Run,
    [switch]$Fair,
    [string]$Grep
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Assert-E2eDatabase([string]$url) {
    if ([string]::IsNullOrWhiteSpace($url) -or $url -notmatch '^postgres(?:ql)?(?:\+[^:]+)?://') {
        throw 'E2eDatabaseUrl must be an explicit PostgreSQL URL.'
    }
    $database = ([uri]$url).AbsolutePath.Trim('/')
    if ([string]::IsNullOrWhiteSpace($database) -or $database -in @('justice', 'postgres')) {
        throw 'Refusing to use the normal development database; provide a dedicated E2E database.'
    }
}
function Get-E2eAdminDatabaseUrl([string]$url, [string]$adminUrl) {
    if (-not [string]::IsNullOrWhiteSpace($adminUrl)) {
        Assert-E2eDatabase $adminUrl
        if (([uri]$adminUrl).AbsolutePath.Trim('/') -ne ([uri]$url).AbsolutePath.Trim('/')) {
            throw 'E2eAdminDatabaseUrl must target the same dedicated E2E database.'
        }
        return $adminUrl
    }

    if ($url -match '://app:app_pw@') {
        return $url -replace '://app:app_pw@', '://db_admin:db_admin_pw@'
    }
    return $url
}
function ConvertTo-PsycopgUrl([string]$url) {
    if ($url -match '^postgres(?:ql)?://') {
        return $url -replace '^postgres(?:ql)?://', 'postgresql+psycopg://'
    }
    return $url
}

try {
    Assert-E2eDatabase $E2eDatabaseUrl
    $e2eAdminUrl = Get-E2eAdminDatabaseUrl $E2eDatabaseUrl $E2eAdminDatabaseUrl
    $E2eDatabaseUrl = ConvertTo-PsycopgUrl $E2eDatabaseUrl
    $e2eAdminUrl = ConvertTo-PsycopgUrl $e2eAdminUrl
}
catch { Write-Error $_; exit 1 }
if ($ValidateOnly) { Write-Host 'E2E database URL accepted.'; exit 0 }
if (-not $Run) { throw 'Pass -Run to start services and invoke Playwright, or -ValidateOnly to check configuration.' }

$env:DATABASE_URL = $E2eDatabaseUrl
$env:DB_ADMIN_URL = $e2eAdminUrl
# The role bootstrap logs in once per role on every run. Keep production's
# limiter unchanged while preventing repeated local smoke runs from exhausting
# the five-minute login window.
$env:LOGIN_RATE_LIMIT = '100/minute'
$env:LOGIN_ACCOUNT_RATE_LIMIT = '100/minute'
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    # Git worktrees do not duplicate the ignored virtual environment. Reuse
    # the environment from the main checkout while keeping code and services
    # rooted in this worktree.
    $commonGitDir = (& git -C $root rev-parse --path-format=absolute --git-common-dir 2>$null)
    if ($LASTEXITCODE -eq 0 -and $commonGitDir) {
        $commonRoot = Split-Path -Parent $commonGitDir.Trim()
        $python = Join-Path $commonRoot 'backend\.venv\Scripts\python.exe'
    }
}
if (-not (Test-Path $python)) { throw 'backend\.venv is missing in this worktree and its main checkout.' }
Push-Location (Join-Path $root 'backend')
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'E2E migrations failed.' }
    $seedArgs = @('-m', 'app.scripts.seed', '--db-url', $E2eDatabaseUrl, '--clear')
    if ($Fair) { $seedArgs += '--fair' }
    & $python @seedArgs
    if ($LASTEXITCODE -ne 0) { throw 'E2E seed failed.' }
} finally { Pop-Location }

$frontend = Join-Path $root 'frontend'
$backend = Join-Path $root 'backend'
foreach ($port in @(8000, 5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the existing dev stack before running the E2E runner."
    }
}
Write-Host 'Starting the existing development services with the explicitly selected E2E database.'
$server = Start-Process -FilePath $python -ArgumentList 'run_dev_server.py' -WorkingDirectory $backend -PassThru
$web = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' -WorkingDirectory $frontend -PassThru
try {
    function Wait-E2eUrl([string]$url, [string]$label) {
        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline) {
            try {
                $response = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
            } catch { }
            Start-Sleep -Seconds 1
        }
        throw "$label health check timed out."
    }
    Wait-E2eUrl 'http://localhost:8000/api/health' 'Backend'
    Wait-E2eUrl 'http://localhost:5173' 'Frontend'
    $args = @('test')
    if ($Grep) { $args += @('--grep', $Grep) }
    Push-Location (Join-Path $root 'frontend'); try { npx playwright @args } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Playwright failed.' }
} finally {
    Stop-Process -Id $server.Id, $web.Id -Force -ErrorAction SilentlyContinue
}
