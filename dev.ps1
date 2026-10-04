#Requires -Version 5.1
<#
.SYNOPSIS
    Start the dev stack. Native app processes are the default; -Docker runs the full Compose stack.
    All services stream logs here with colored prefixes.

.PARAMETER TelegramBot
    Include the Telegram bot.

.PARAMETER ExchangeCalendarWorker
    Include the opt-in Exchange calendar worker.

.PARAMETER Docker
    Run the complete Docker Compose stack in the foreground.

.EXAMPLE
    .\dev.ps1                         # native backend + frontend (default)
    .\dev.ps1 -TelegramBot            # native backend + frontend + bot
    .\dev.ps1 -ExchangeCalendarWorker # include the Exchange calendar worker
    .\dev.ps1 -Docker                 # full Compose stack
    .\dev.ps1 -Docker -TelegramBot    # include the bot in Compose
#>
param([switch]$TelegramBot, [switch]$ExchangeCalendarWorker, [switch]$Docker)

$root = $PSScriptRoot
if ($Docker) {
    # Keep the native default workflow available while allowing the complete
    # app and observability stack to run together in Docker Compose.
    & (Join-Path $root 'scripts\dev-certs.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Local storage certificate setup failed.' }
    $composeServices = @('seaweedfs', 'seaweedfs-s3-proxy', 'seaweedfs-init', 'db', 'redis', 'loki', 'prometheus', 'grafana', 'backend', 'file-authorization', 'file-gateway', 'frontend')
    if ($TelegramBot) { $composeServices += 'telegram-bot' }
    if ($ExchangeCalendarWorker) { $composeServices += 'exchange-calendar-worker' }

    Write-Host '[dev] Starting the Docker Compose stack (Ctrl+C stops the attached services)...' -ForegroundColor Cyan
    Write-Host '  Frontend : http://localhost:5173' -ForegroundColor White
    Write-Host '  Backend  : http://localhost:8000/docs' -ForegroundColor White
    $previousGrafanaPort = $env:GRAFANA_PORT
    if (-not $env:GRAFANA_PORT -and (Test-Path (Join-Path $root '.env'))) {
        $configuredPort = Get-Content (Join-Path $root '.env') | Where-Object { $_ -match '^GRAFANA_PORT=' } | Select-Object -Last 1
        if ($configuredPort) { $env:GRAFANA_PORT = ($configuredPort -split '=', 2)[1] }
    }
    if (-not $env:GRAFANA_PORT) { $env:GRAFANA_PORT = '3000' }
    if ($env:GRAFANA_PORT -eq '3000') {
        try {
            $portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, 3000)
            $portProbe.Start()
            $portProbe.Stop()
        } catch {
            $env:GRAFANA_PORT = '12080'
            Write-Host '[dev] Host port 3000 is reserved; using Grafana port 12080.' -ForegroundColor Yellow
        }
    }
    Write-Host ("  Grafana  : http://localhost:{0}" -f $env:GRAFANA_PORT) -ForegroundColor White
    & docker compose --project-directory $root up --build $composeServices
    $composeExitCode = $LASTEXITCODE
    if ($null -eq $previousGrafanaPort) { Remove-Item Env:GRAFANA_PORT -ErrorAction SilentlyContinue } else { $env:GRAFANA_PORT = $previousGrafanaPort }
    exit $composeExitCode
}

# ── Parse .env.defaults + .env (secrets/overrides win), replacing
#    Docker-internal 'db' hostname with localhost ─────────────────────────────
$envVars = @{}
foreach ($envFile in @("$root\.env.defaults", "$root\.env")) {
    if (-not (Test-Path $envFile)) { continue }
    Get-Content $envFile | Where-Object { $_ -match '^[A-Z_]+=.+$' } | ForEach-Object {
        $parts = $_ -split '=', 2
        $envVars[$parts[0]] = $parts[1]
    }
}
$localDbUrl    = $envVars['DATABASE_URL'] -replace '@db:', '@localhost:'
$localAdminUrl = $envVars['DB_ADMIN_URL']  -replace '@db:', '@localhost:'
$localRedisUrl = $envVars['REDIS_URL'] -replace '://redis:', '://localhost:'

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

# Native mode: every `docker compose` call below also loads the overlay that
# publishes the storage services (S3 proxy, file gateway) on loopback.
$env:COMPOSE_FILE = "$root\docker-compose.yml;$root\docker-compose.dev-native.yml"

# ── Stop Docker app containers so their ports are free ────────────────────────
Write-Host "[dev] Stopping Docker app containers (keeping DB)..." -ForegroundColor Yellow
try { docker compose stop backend frontend telegram-bot exchange-calendar-worker *>$null } catch {}

# ── Kill all stale dev-server processes ───────────────────────────────────────
Write-Host "[dev] Killing stale backend/frontend processes..." -ForegroundColor Yellow

# Kill by port first — most reliable, catches child processes that WMI misses
foreach ($port in @(8000, 5173)) {
    $portPids = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $portPids) {
        Write-Host "[dev]   killing pid=$procId on :$port" -ForegroundColor DarkYellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

# Kill any python process running run_dev_server.py or uvicorn for this project
Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'run_dev_server|uvicorn|run_dev_bot|app\.exchange_calendar_worker' } |
    ForEach-Object {
        Write-Host "[dev]   killing python pid=$($_.ProcessId) ($($_.CommandLine.Substring(0, [Math]::Min(60,$_.CommandLine.Length)))...)" -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Kill any node/vite process
Get-WmiObject Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -match 'vite|concurrently' } |
    ForEach-Object {
        Write-Host "[dev]   killing node pid=$($_.ProcessId)" -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Wait until both ports are actually free (up to 10s) instead of a flat sleep
$deadline = (Get-Date).AddSeconds(10)
foreach ($port in @(8000, 5173)) {
    while ((Get-Date) -lt $deadline) {
        $still = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if (-not $still) { break }
        Write-Host "[dev]   waiting for :$port to be released..." -ForegroundColor DarkYellow
        Start-Sleep -Milliseconds 300
    }
    $still = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($still) { Write-Warning "[dev] Port $port still in use after 10s — proceeding anyway" }
}

# ── Start only the DB ─────────────────────────────────────────────────────────
# docker-compose.yml references gitignored env files (deploy/seaweedfs/secrets/*.env)
# and compose validates them for every service, even with --no-deps. Generate them
# once (idempotent) so the DB containers can start.
$seaweedCertDir = Join-Path $root 'deploy\seaweedfs\certs\seaweedfs'
$seaweedCert = Join-Path $seaweedCertDir 'public.crt'
if (Test-Path $seaweedCert) {
    # Certs generated before the native-dev overlay lack the "localhost" SAN the
    # native backend needs to verify the published S3 proxy; regenerate that one.
    $san = ([System.Security.Cryptography.X509Certificates.X509Certificate2]::new($seaweedCert).Extensions |
        Where-Object { $_.Oid.Value -eq '2.5.29.17' } | ForEach-Object { $_.Format($false) }) -join ' '
    if ($san -notmatch 'localhost') {
        Write-Host "[dev] Regenerating SeaweedFS TLS cert (adding localhost SAN)..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $seaweedCertDir
        & (Join-Path $root 'scripts\dev-certs.ps1')
    }
}
if (-not (Test-Path (Join-Path $root 'deploy\seaweedfs\secrets\initializer.env'))) {
    Write-Host "[dev] Generating local storage certs/secrets (first run)..." -ForegroundColor Cyan
    & (Join-Path $root 'scripts\dev-certs.ps1')
    if ($LASTEXITCODE -ne 0) { Write-Error '[dev] Local storage certificate setup failed.'; exit 1 }
}
Write-Host "[dev] Starting DB + Redis + observability containers..." -ForegroundColor Cyan
# Prometheus uses the native-backend target while dev.ps1 runs Uvicorn on the host.
$previousPrometheusConfig = $env:PROMETHEUS_CONFIG
$env:PROMETHEUS_CONFIG = ($root -replace '\\', '/') + '/deploy/observability/prometheus.native.yml'
#    --no-deps: prometheus's `depends_on: backend` would otherwise pull the
#    dockerized backend container up too, fighting the natively-run backend
#    for port 8000 (this script stops the dockerized backend above precisely
#    so the native one can bind that port).
$dbOut = docker compose up db redis loki prometheus grafana -d --no-deps 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($dbOut -match "ports are not available|access a socket") {
        # Windows reserved the port range that includes 5432 (Hyper-V/WinNAT).
        # Reset WinNAT to release it, then retry.
        Write-Host "[dev] Port 5432 reserved by Windows — resetting WinNAT (UAC prompt may appear)..." -ForegroundColor Yellow
        Start-Process powershell -Verb RunAs -ArgumentList '-Command', 'net stop winnat; net start winnat' -Wait -WindowStyle Hidden
        Start-Sleep -Seconds 2
        $dbOut = docker compose up db redis loki prometheus grafana -d --no-deps 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[dev] DB container failed to start: $dbOut"; exit 1
    }
}

if ($null -eq $previousPrometheusConfig) {
    Remove-Item Env:PROMETHEUS_CONFIG -ErrorAction SilentlyContinue
} else {
    $env:PROMETHEUS_CONFIG = $previousPrometheusConfig
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

Write-Host "[dev] Waiting for Redis to be healthy..." -ForegroundColor Cyan
$redisContainer = docker compose ps -q redis
for ($i = 0; $i -lt 30; $i++) {
    $redisHealth = docker inspect --format '{{.State.Health.Status}}' $redisContainer 2>$null
    if ($redisHealth -eq "healthy") { break }
    Start-Sleep -Seconds 1
}
if ($redisHealth -ne "healthy") { Write-Error "Redis did not become healthy in time."; exit 1 }
Write-Host "[dev] Redis ready." -ForegroundColor Green

# ── Run migrations against localhost ─────────────────────────────────────────
Write-Host "[dev] Running migrations..." -ForegroundColor Cyan
$env:DATABASE_URL = $localDbUrl
$env:DB_ADMIN_URL = $localAdminUrl
$env:REDIS_URL = $localRedisUrl
$env:LOKI_URL = "http://localhost:3100"
$env:ENVIRONMENT = $envVars['ENVIRONMENT']
# Storage: the native backend talks to the S3 proxy published by the overlay,
# using the API identity from the generated secrets (same file the Docker backend uses).
Get-Content (Join-Path $root 'deploy\seaweedfs\secrets\api.env') | Where-Object { $_ -match '^[A-Z_]+=.+$' } | ForEach-Object {
    $parts = $_ -split '=', 2
    Set-Item -Path "Env:$($parts[0])" -Value $parts[1]
}
$env:STORAGE_ENDPOINT_URL = 'https://localhost:19443'
$env:STORAGE_CA_BUNDLE_PATH = Join-Path $root 'deploy\seaweedfs\certs\ca.crt'
$env:VITE_FILE_GATEWAY_URL = 'http://localhost:18080'
Push-Location "$root\backend"
& $venvPy -m alembic upgrade head
$migrationExitCode = $LASTEXITCODE
Pop-Location
if ($migrationExitCode -ne 0) {
    Write-Error "[dev] Migrations failed (exit code $migrationExitCode) — fix the error above before starting services. A partial/failed migration run (e.g. the app DB role from migration 0001 never created) will make the backend fail to connect."
    exit 1
}
Write-Host "[dev] Migrations done." -ForegroundColor Green

# ── Storage stack (Docker): SeaweedFS -> bucket init -> authz + file gateway ──
# Staged with --no-deps because file-gateway `depends_on: backend`, which would
# start the Dockerized backend and fight the native one for port 8000.
Write-Host "[dev] Starting storage containers (SeaweedFS, S3 proxy)..." -ForegroundColor Cyan
docker compose up -d --no-deps --wait seaweedfs seaweedfs-s3-proxy
if ($LASTEXITCODE -ne 0) { Write-Error "[dev] SeaweedFS failed to start."; exit 1 }
docker compose run --rm --no-deps --build seaweedfs-init
if ($LASTEXITCODE -ne 0) { Write-Error "[dev] Storage bucket initialization failed."; exit 1 }
docker compose up -d --no-deps --build file-authorization file-gateway
if ($LASTEXITCODE -ne 0) { Write-Error "[dev] file-authorization/file-gateway failed to start."; exit 1 }
Write-Host "[dev] Storage ready (S3 https://localhost:19443, file gateway http://localhost:18080)." -ForegroundColor Green

# ── Build service list for concurrently ──────────────────────────────────────
$names  = [System.Collections.Generic.List[string]]::new()
$colors = [System.Collections.Generic.List[string]]::new()
$cmds   = [System.Collections.Generic.List[string]]::new()

$names.Add("backend");  $colors.Add("cyan");
$cmds.Add("cd /d `"$root\backend`" && `"$venvPy`" run_dev_server.py")

$names.Add("frontend"); $colors.Add("yellow")
$cmds.Add("cd /d `"$root\frontend`" && npm run dev")

if ($TelegramBot) {
    $names.Add("bot");  $colors.Add("magenta")
    # LOKI_APP_LABEL distinguishes the bot's Loki stream (app="justice-bot")
    # from the backend's (app="justice-backend", the default) so Grafana can
    # filter one from the other. Set only for this command's cmd.exe shell —
    # LOKI_URL itself is already inherited from the parent process env above.
    $cmds.Add("set LOKI_APP_LABEL=justice-bot && cd /d `"$root\backend`" && `"$venvPy`" run_dev_bot.py")
}

if ($ExchangeCalendarWorker) {
    $names.Add("exchange-calendar"); $colors.Add("blue")
    # Keep the Exchange worker's Loki stream separate from API and bot logs.
    $cmds.Add("set LOKI_APP_LABEL=justice-exchange-calendar && cd /d `"$root\backend`" && `"$venvPy`" -m app.exchange_calendar_worker")
}

# ── Kill any stale bot processes ─────────────────────────────────────────────
if ($TelegramBot) {
    $botProcs = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'bot\.main|run_dev_bot\.py' }
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
Write-Host "  Backend  : http://localhost:8000/api" -ForegroundColor White
Write-Host "  Press Ctrl+C to stop all services." -ForegroundColor DarkGray
Write-Host ""

$concurrentlyArgs = @(
    "--names",         ($names  -join ","),
    "--prefix-colors", ($colors -join ",")
) + $cmds.ToArray()

npx --yes concurrently @concurrentlyArgs
