[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectName = "justice-task8-e2e"
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeFiles = @(
    "--project-directory", $projectDirectory,
    "-f", (Join-Path $projectDirectory "docker-compose.yml"),
    "-f", (Join-Path $projectDirectory "docker-compose.task8-e2e.yml")
)
$composeArgs = @("compose", "--profile", "storage-maintenance", "-p", $projectName) + $composeFiles
$startedByThisScript = $false
$hadFrontendPort = $null
$previousFrontendPort = $null
$hadGimelimFixture = $null
$previousGimelimFixture = $null

function Invoke-Compose([string[]]$Arguments) {
    & docker @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }
}

function Assert-NoExistingTask8Project {
    $ids = & docker @composeArgs ps -aq
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the dedicated Task 8 Compose project."
    }
    if ($ids) {
        throw "The dedicated Compose project '$projectName' already has containers. Stop and inspect that project before reusing it; this script will not remove pre-existing resources."
    }

    $volumes = & docker volume ls -q --filter "label=com.docker.compose.project=$projectName"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Docker volumes for the dedicated Task 8 project."
    }
    if ($volumes) {
        throw "The dedicated Compose project '$projectName' already has volumes. Inspect them before reusing this name; this script will not remove pre-existing resources."
    }

    $networks = & docker network ls -q --filter "label=com.docker.compose.project=$projectName"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Docker networks for the dedicated Task 8 project."
    }
    if ($networks) {
        throw "The dedicated Compose project '$projectName' already has networks. Inspect them before reusing this name; this script will not remove pre-existing resources."
    }
}

function Remove-OwnedTask8Project {
    $containers = @(& docker ps -aq --filter "label=com.docker.compose.project=$projectName")
    $volumes = @(& docker volume ls -q --filter "label=com.docker.compose.project=$projectName")
    $networks = @(& docker network ls -q --filter "label=com.docker.compose.project=$projectName")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to verify ownership labels for Task 8 cleanup."
    }

    foreach ($containerId in $containers) {
        $details = (& docker inspect $containerId | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -ne 0 -or $details.Config.Labels.'com.docker.compose.project' -ne $projectName) {
            throw "Refusing cleanup: container '$containerId' is not labeled for '$projectName'."
        }
    }
    foreach ($volumeName in $volumes) {
        $details = (& docker volume inspect $volumeName | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -ne 0 -or $details.Labels.'com.docker.compose.project' -ne $projectName) {
            throw "Refusing cleanup: volume '$volumeName' is not labeled for '$projectName'."
        }
    }
    foreach ($networkId in $networks) {
        $details = (& docker network inspect $networkId | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -ne 0 -or $details.Labels.'com.docker.compose.project' -ne $projectName) {
            throw "Refusing cleanup: network '$networkId' is not labeled for '$projectName'."
        }
    }

    if ($containers.Count -gt 0 -or $volumes.Count -gt 0 -or $networks.Count -gt 0) {
        Invoke-Compose @("down", "--volumes", "--remove-orphans")
    }
}

try {
    Assert-NoExistingTask8Project
    do {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
        $listener.Start()
        $frontendPort = $listener.LocalEndpoint.Port
        $listener.Stop()
    } while ($frontendPort -eq 10080) # Chromium rejects this otherwise-free local test port.
    $hadFrontendPort = $null -ne [Environment]::GetEnvironmentVariable("TASK8_E2E_FRONTEND_PORT", "Process")
    $previousFrontendPort = $env:TASK8_E2E_FRONTEND_PORT
    $env:TASK8_E2E_FRONTEND_PORT = [string]$frontendPort

    # The name was verified empty above, so any partial resources from a failed
    # `up` are owned by this invocation and can be removed after label checks.
    $startedByThisScript = $true
    Invoke-Compose @("up", "--build", "--detach", "frontend")

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$frontendPort/api/auth/exemption-types" -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
            # Compose services start asynchronously; retry until the migrated API
            # schema is queryable through the same proxy that Playwright uses.
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw "The isolated backend did not become ready through the frontend proxy."
    }

    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.seed")
    Invoke-Compose @("run", "--build", "--rm", "--no-deps", "file-storage-maintenance", "python", "-m", "app.storage.maintenance_cli", "preflight")
    $gimelimFixture = & docker @composeArgs exec -T backend python -m app.scripts.storage_e2e_fixture
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the isolated gimelim attachment fixture."
    }
    $gimelimDismissalId = ($gimelimFixture -join "`n" | ConvertFrom-Json).dismissal_id
    $preflightOutput = & docker @composeArgs exec -T file-gateway python -m app.scripts.storage_gateway_preflight 2>&1
    $preflightExitCode = $LASTEXITCODE
    $preflightOutput | ForEach-Object { Write-Host $_ }
    if ($preflightExitCode -ne 0) {
        $authorizationDiagnostics = & docker @composeArgs logs --since=1m file-authorization 2>&1
        $authorizationDiagnostics |
            Select-String -Pattern "Traceback|ERROR|Exception|POST /_internal/file-authorizations" |
            ForEach-Object { Write-Host "[Task 8 authorization preflight diagnostic] $($_.Line)" }
        throw "The isolated gateway-to-authorization mTLS preflight failed."
    }
    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.storage_lifecycle_preflight", "write")
    Invoke-Compose @("run", "--rm", "--no-deps", "seaweedfs-init")
    Invoke-Compose @("up", "-d", "--wait", "--wait-timeout", "120", "--force-recreate", "seaweedfs", "seaweedfs-s3-proxy")
    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.storage_lifecycle_preflight", "verify")
    Invoke-Compose @("stop", "seaweedfs")
    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.storage_lifecycle_preflight", "outage")
    Invoke-Compose @("up", "-d", "--wait", "--wait-timeout", "120", "--force-recreate", "seaweedfs", "seaweedfs-s3-proxy")
    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.storage_lifecycle_preflight", "verify")
    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.storage_lifecycle_preflight", "tls-negative")
    Invoke-Compose @("exec", "-T", "backend", "python", "-m", "app.scripts.storage_lifecycle_preflight", "runtime-iam")
    Invoke-Compose @("exec", "-T", "file-gateway", "python", "-m", "app.scripts.storage_lifecycle_preflight", "gateway-iam")
    Invoke-Compose @("run", "--build", "--rm", "--no-deps", "file-storage-maintenance", "python", "-m", "app.scripts.storage_lifecycle_preflight", "maintenance-iam")
    $hadGimelimFixture = $null -ne [Environment]::GetEnvironmentVariable("STORAGE_E2E_GIMELIM_DISMISSAL_ID", "Process")
    $previousGimelimFixture = $env:STORAGE_E2E_GIMELIM_DISMISSAL_ID
    & python (Join-Path $PSScriptRoot "verify_task8_workbook.py")
    if ($LASTEXITCODE -ne 0) {
        throw "The isolated Excel workbook fixture did not validate."
    }

    Push-Location (Join-Path $PSScriptRoot "..\frontend")
    $hadBaseUrl = $null -ne [Environment]::GetEnvironmentVariable("E2E_BASE_URL", "Process")
    $previousBaseUrl = $env:E2E_BASE_URL
    $hadIsolatedFlag = $null -ne [Environment]::GetEnvironmentVariable("STORAGE_E2E_ISOLATED", "Process")
    $previousIsolatedFlag = $env:STORAGE_E2E_ISOLATED
    try {
        $env:E2E_BASE_URL = "http://localhost:$frontendPort"
        $env:STORAGE_E2E_ISOLATED = "1"
        $env:STORAGE_E2E_GIMELIM_DISMISSAL_ID = $gimelimDismissalId
        & npx playwright test --project=desktop tests/e2e/file-downloads.spec.ts
        $testExitCode = $LASTEXITCODE
        if ($testExitCode -ne 0) {
            $gatewayDiagnostics = & docker @composeArgs logs --since=2m file-gateway 2>&1
            $gatewayDiagnostics |
                Select-String -Pattern "File download authorization failed|File object read failed" |
                ForEach-Object { Write-Host "[Task 8 gateway diagnostic] $($_.Line)" }
            $authorizationDiagnostics = & docker @composeArgs logs --since=2m file-authorization 2>&1
            $authorizationDiagnostics |
                Select-String -Pattern "Traceback|ERROR|Exception|POST /_internal/file-authorizations" |
                ForEach-Object { Write-Host "[Task 8 authorization diagnostic] $($_.Line)" }
            throw "The storage browser E2E suite failed with exit code $testExitCode"
        }
    }
    finally {
        if ($hadBaseUrl) { $env:E2E_BASE_URL = $previousBaseUrl }
        else { Remove-Item Env:E2E_BASE_URL -ErrorAction SilentlyContinue }
        if ($hadIsolatedFlag) { $env:STORAGE_E2E_ISOLATED = $previousIsolatedFlag }
        else { Remove-Item Env:STORAGE_E2E_ISOLATED -ErrorAction SilentlyContinue }
        Pop-Location
    }
}
finally {
    if ($null -ne $hadFrontendPort) {
        if ($hadFrontendPort) { $env:TASK8_E2E_FRONTEND_PORT = $previousFrontendPort }
        else { Remove-Item Env:TASK8_E2E_FRONTEND_PORT -ErrorAction SilentlyContinue }
    }
    if ($null -ne $hadGimelimFixture) {
        if ($hadGimelimFixture) { $env:STORAGE_E2E_GIMELIM_DISMISSAL_ID = $previousGimelimFixture }
        else { Remove-Item Env:STORAGE_E2E_GIMELIM_DISMISSAL_ID -ErrorAction SilentlyContinue }
    }
    if ($startedByThisScript) {
        Remove-OwnedTask8Project
    }
}
