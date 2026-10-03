#Requires -Version 5.1
<#
.SYNOPSIS
    Runs the real-provider (Keycloak) OIDC SSO browser journeys against a disposable stack.

.DESCRIPTION
    Starts throwaway containers (oidc-e2e-pg, oidc-e2e-redis, oidc-e2e-keycloak) on
    non-default ports, migrates and seeds a fresh database, starts the backend (:8410)
    and Vite (:5183) natively with OIDC_* pointing at Keycloak, runs
    playwright.oidc.config.ts, then stops everything it started.

    The issuer is http://127.0.0.1:8411/realms/justice-test while the app is on
    http://localhost:5183: a different *site*, so the cross-site callback cookie
    behaviour is genuinely exercised. (*.localhost issuer hosts are not used: Python on
    Windows cannot resolve them and the backend only allows literal loopback hosts.)

.PARAMETER KeepUp
    Leave the stack running afterwards (stop it later with -Down).
.PARAMETER NoOidc
    Start the backend WITHOUT any OIDC_* settings and run only the 'no OIDC settings' journey.
.PARAMETER Down
    Only stop/remove what a previous run left behind.
.PARAMETER PlaywrightArgs
    Extra arguments passed to `playwright test` (for example -g "ambiguous").
#>
param([switch]$KeepUp, [switch]$Down, [switch]$NoOidc, [string[]]$PlaywrightArgs = @())

$ErrorActionPreference = 'Continue'  # native tools write progress to stderr; failures are checked via $LASTEXITCODE
$here    = $PSScriptRoot
$root    = (Resolve-Path (Join-Path $here '..\..\..\..')).Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$py      = Join-Path $backend '.venv\Scripts\python.exe'
$logs    = Join-Path $root '.oidc-e2e-logs'
$containers = @('oidc-e2e-keycloak', 'oidc-e2e-redis', 'oidc-e2e-pg')
$ports = @(8410, 5183)

function Stop-Stack {
    $ErrorActionPreference = 'Continue'
    foreach ($port in $ports) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    foreach ($c in $containers) { docker stop $c *>$null; docker rm $c *>$null }
}

if ($Down) { Stop-Stack; return }

New-Item -ItemType Directory -Force $logs | Out-Null
Stop-Stack   # clean slate: only our own named containers and our two ports

$dbUrl    = 'postgresql+psycopg://app:app_pw@localhost:55440/justice'
$adminUrl = 'postgresql+psycopg://db_admin:db_admin_pw@localhost:55440/justice'
$exit = 1
try {
    docker run -d --name oidc-e2e-pg -p 127.0.0.1:55440:5432 -e POSTGRES_USER=db_admin -e POSTGRES_PASSWORD=db_admin_pw -e POSTGRES_DB=justice --memory 200m postgres:16-alpine postgres -c timezone=Asia/Jerusalem | Out-Null
    docker run -d --name oidc-e2e-redis -p 127.0.0.1:56392:6379 --memory 64m redis:7-alpine | Out-Null
    docker run -d --name oidc-e2e-keycloak -p 127.0.0.1:8411:8080 --memory 900m -e JAVA_OPTS_KC_HEAP='-Xms128m -Xmx512m' -e KC_HOSTNAME=http://127.0.0.1:8411 -v "$here\justice-test-realm.json:/opt/keycloak/data/import/justice-test-realm.json:ro" quay.io/keycloak/keycloak:26.0 start-dev --import-realm | Out-Null

    $env:DATABASE_URL = $dbUrl; $env:DB_ADMIN_URL = $adminUrl; $env:REDIS_URL = 'redis://localhost:56392/0'
    $env:ENVIRONMENT = 'development'
    # Wait for Postgres (alembic fails fast otherwise).
    for ($i = 0; $i -lt 40; $i++) {
        if ((Test-NetConnection 127.0.0.1 -Port 55440 -WarningAction SilentlyContinue).TcpTestSucceeded) { Start-Sleep 3; break }
        Start-Sleep 2
    }
    Push-Location $backend
    & $py -m alembic upgrade head; if ($LASTEXITCODE) { throw 'migrations failed' }
    & $py -m app.scripts.seed; if ($LASTEXITCODE) { throw 'seed failed' }
    $env:PYTHONPATH = '.'
    & $py (Join-Path $here 'seed_identities.py'); if ($LASTEXITCODE) { throw 'identity seed failed' }
    Pop-Location

    $env:COOKIE_SECURE = 'false'
    if ($NoOidc) { $PlaywrightArgs = @('-g', 'no OIDC settings') + $PlaywrightArgs; $env:E2E_OIDC_DISABLED = '1' }
    $env:FRONTEND_URL = 'http://localhost:5183'; $env:ALLOWED_ORIGINS = 'http://localhost:5183'
    if (-not $NoOidc) { $env:OIDC_ISSUER = 'http://127.0.0.1:8411/realms/justice-test' }
    if (-not $NoOidc) { $env:OIDC_CLIENT_ID = 'justice-test-client' }
    if (-not $NoOidc) { $env:OIDC_CLIENT_SECRET = 'justice-test-only-client-secret' }
    if (-not $NoOidc) { $env:OIDC_REDIRECT_URI = 'http://localhost:8410/api/auth/oidc/callback' }
    if (-not $NoOidc) { $env:OIDC_ALLOW_INSECURE_LOCAL = 'true' }
    $env:OIDC_RATE_LIMIT = '200/minute'; $env:LOGIN_RATE_LIMIT = '1000/minute'
    Start-Process -FilePath $py -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8410' -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput "$logs\backend.log" -RedirectStandardError "$logs\backend.err.log"
    # Serve the production build (vite preview) rather than the dev server: the dev server's on-demand
    # transforms stalled proxied API calls on a small machine. The preview server has the same /api proxy.
    Push-Location $frontend; & npx vite build; if ($LASTEXITCODE) { throw 'frontend build failed' }; Pop-Location
    $env:VITE_BACKEND_URL = 'http://127.0.0.1:8410'  # uvicorn listens on IPv4 only; localhost may resolve to ::1 first and stall the proxy
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c npx vite preview --port 5183 --strictPort' -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput "$logs\vite.log" -RedirectStandardError "$logs\vite.err.log"

    # Wait for backend, Vite proxy and Keycloak discovery.
    $ready = $false
    for ($i = 0; $i -lt 90 -and -not $ready; $i++) {
        try {
            $s = Invoke-RestMethod http://localhost:5183/api/auth/oidc/status -TimeoutSec 3
            $d = Invoke-RestMethod http://127.0.0.1:8411/realms/justice-test/.well-known/openid-configuration -TimeoutSec 3
            if (($s.enabled -or $NoOidc) -and $d.issuer) { $ready = $true }
        } catch { Start-Sleep 3 }
    }
    if (-not $ready) { throw "stack did not become ready; see $logs and 'docker logs oidc-e2e-keycloak'" }

    # Warm-up: the first OIDC discovery and the first Keycloak login page are slow on a cold start.
    if (-not $NoOidc) { try {
        $start = Invoke-WebRequest http://localhost:8410/api/auth/oidc/start -MaximumRedirection 0 -UseBasicParsing -ErrorAction SilentlyContinue -TimeoutSec 120
        $loc = $start.Headers['Location']
        if ($loc) { Invoke-WebRequest $loc -UseBasicParsing -TimeoutSec 180 | Out-Null }
    } catch {
        $loc = $_.Exception.Response.Headers['Location']
        if ($loc) { try { Invoke-WebRequest $loc -UseBasicParsing -TimeoutSec 180 | Out-Null } catch {} }
    } }

    Push-Location $frontend
    & npx playwright test --config=playwright.oidc.config.ts @PlaywrightArgs
    $exit = $LASTEXITCODE
    Pop-Location
}
finally {
    if (-not $KeepUp) { Stop-Stack }
}
exit $exit
