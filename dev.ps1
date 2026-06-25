#Requires -Version 5.1
<#
.SYNOPSIS
    Start the full dev stack in one window (DB only in Docker).
    All services stream logs here with colored prefixes.

.PARAMETER NoBot
    Skip the Telegram bot.

.EXAMPLE
    .\dev.ps1
    .\dev.ps1 -NoBot
#>
param([switch]$NoBot)

$root = $PSScriptRoot

# ── Parse .env, replacing Docker-internal 'db' hostname with localhost ────────
$envVars = @{}
Get-Content "$root\.env" | Where-Object { $_ -match '^[A-Z_]+=.+$' } | ForEach-Object {
    $parts = $_ -split '=', 2
    $envVars[$parts[0]] = $parts[1]
}
$localDbUrl    = $envVars['DATABASE_URL'] -replace '@db:', '@localhost:'
$localAdminUrl = $envVars['DB_ADMIN_URL']  -replace '@db:', '@localhost:'

# ── PyPI mirror support ───────────────────────────────────────────────────────
# pip reads PIP_INDEX_URL from the environment automatically.
# Set it in your shell or add PIP_INDEX_URL=https://your.mirror/simple/ to .env.
if ($envVars.ContainsKey('PIP_INDEX_URL') -and -not $env:PIP_INDEX_URL) {
    $env:PIP_INDEX_URL = $envVars['PIP_INDEX_URL']
}

# ── Python virtual environment ────────────────────────────────────────────────
$venvPy  = "$root\backend\.venv\Scripts\python.exe"
$venvPip = "$root\backend\.venv\Scripts\pip.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[dev] Creating Python virtual environment..." -ForegroundColor Cyan
    python -m venv "$root\backend\.venv"
    Write-Host "[dev] Installing Python dependencies..." -ForegroundColor Cyan
    Push-Location "$root\backend"
    & $venvPip install -e ".[dev]"
    Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Error "[dev] pip install failed"; exit 1 }
}

# ── Node.js dependencies ──────────────────────────────────────────────────────
if (-not (Test-Path "$root\frontend\node_modules\.bin\vite")) {
    Write-Host "[dev] Installing frontend dependencies (npm install)..." -ForegroundColor Cyan
    Push-Location "$root\frontend"
    npm install
    Pop-Location
}

# ── Helper: kill whatever process is listening on a TCP port ─────────────────
function Stop-PortProcess([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
        return $true
    }
    return $false
}

# ── Stop Docker app containers so their ports are free ────────────────────────
Write-Host "[dev] Stopping Docker app containers (keeping DB)..." -ForegroundColor Yellow
try { docker compose stop backend frontend telegram-bot *>$null } catch {}

# ── Kill any native processes still holding dev ports ────────────────────────
Write-Host "[dev] Freeing ports 8000 and 5173..." -ForegroundColor Yellow
if (Stop-PortProcess 8000) { Write-Host "[dev]   killed process on :8000" -ForegroundColor DarkYellow }
if (Stop-PortProcess 5173) { Write-Host "[dev]   killed process on :5173" -ForegroundColor DarkYellow }

# ── Start only the DB ─────────────────────────────────────────────────────────
Write-Host "[dev] Starting DB container..." -ForegroundColor Cyan
$dbOut = docker compose up db -d 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($dbOut -match "ports are not available|access a socket") {
        # Windows reserved the port range that includes 5432 (Hyper-V/WinNAT).
        # Reset WinNAT to release it, then retry.
        Write-Host "[dev] Port 5432 reserved by Windows — resetting WinNAT (UAC prompt may appear)..." -ForegroundColor Yellow
        Start-Process powershell -Verb RunAs -ArgumentList '-Command', 'net stop winnat; net start winnat' -Wait -WindowStyle Hidden
        Start-Sleep -Seconds 2
        $dbOut = docker compose up db -d 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[dev] DB container failed to start: $dbOut"; exit 1
    }
}

Write-Host "[dev] Waiting for DB to be healthy..." -ForegroundColor Cyan
$dbContainer = docker compose ps -q db
for ($i = 0; $i -lt 30; $i++) {
    $health = docker inspect --format '{{.State.Health.Status}}' $dbContainer 2>$null
    if ($health -eq "healthy") { break }
    Start-Sleep -Seconds 1
}
if ($health -ne "healthy") { Write-Error "DB did not become healthy in time."; exit 1 }
Write-Host "[dev] DB ready." -ForegroundColor Green

# ── Run migrations against localhost ─────────────────────────────────────────
Write-Host "[dev] Running migrations..." -ForegroundColor Cyan
$env:DATABASE_URL = $localDbUrl
$env:DB_ADMIN_URL = $localAdminUrl
Push-Location "$root\backend"
& $venvPy -m alembic upgrade head
Pop-Location
Write-Host "[dev] Migrations done." -ForegroundColor Green

# ── Build service list for concurrently ──────────────────────────────────────
$names  = [System.Collections.Generic.List[string]]::new()
$colors = [System.Collections.Generic.List[string]]::new()
$cmds   = [System.Collections.Generic.List[string]]::new()

$names.Add("backend");  $colors.Add("cyan");
$cmds.Add("cd /d `"$root\backend`" && `"$venvPy`" run_dev_server.py")

$names.Add("frontend"); $colors.Add("yellow")
$cmds.Add("cd /d `"$root\frontend`" && npm run dev")

if (-not $NoBot) {
    $names.Add("bot");  $colors.Add("magenta")
    $cmds.Add("cd /d `"$root\backend`" && `"$venvPy`" run_dev_bot.py")
}

# ── Kill any stale bot processes ─────────────────────────────────────────────
if (-not $NoBot) {
    $botProcs = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'bot\.main' }
    if ($botProcs) {
        Write-Host "[dev] Killing $($botProcs.Count) stale bot process(es)..." -ForegroundColor Yellow
        $botProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
}

# ── Launch ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Dev stack starting..." -ForegroundColor Green
Write-Host "  Frontend : http://localhost:5173" -ForegroundColor White
Write-Host "  Backend  : http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Press Ctrl+C to stop all services." -ForegroundColor DarkGray
Write-Host ""

$concurrentlyArgs = @(
    "--names",         ($names  -join ","),
    "--prefix-colors", ($colors -join ",")
) + $cmds.ToArray()

npx --yes concurrently @concurrentlyArgs
