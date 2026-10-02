[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectName = "justice-storage-migration-e2e"
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeArgs = @(
    "compose", "--profile", "storage-maintenance", "--project-name", $projectName,
    "--project-directory", $projectDirectory,
    "-f", (Join-Path $projectDirectory "docker-compose.yml"),
    "-f", (Join-Path $projectDirectory "docker-compose.task8-e2e.yml"),
    "-f", (Join-Path $projectDirectory "docker-compose.storage-migration-e2e.yml")
)
$startedByThisScript = $false

function Invoke-Compose([string[]]$Arguments) {
    & docker @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Isolated migration rehearsal Compose command failed with exit code $LASTEXITCODE."
    }
}

function Assert-NoExistingProjectResources {
    $containers = @(& docker ps -aq --filter "label=com.docker.compose.project=$projectName")
    $volumes = @(& docker volume ls -q --filter "label=com.docker.compose.project=$projectName")
    $networks = @(& docker network ls -q --filter "label=com.docker.compose.project=$projectName")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Docker resources for the dedicated migration rehearsal project."
    }
    if ($containers.Count -gt 0 -or $volumes.Count -gt 0 -or $networks.Count -gt 0) {
        throw "The dedicated project '$projectName' already owns Docker resources; inspect them before rerunning."
    }
}

function Assert-OwnedResourcesBeforeCleanup {
    $containers = @(& docker ps -aq --filter "label=com.docker.compose.project=$projectName")
    $volumes = @(& docker volume ls -q --filter "label=com.docker.compose.project=$projectName")
    $networks = @(& docker network ls -q --filter "label=com.docker.compose.project=$projectName")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to verify resource ownership for isolated cleanup."
    }
    foreach ($container in $containers) {
        $labelsText = & docker inspect --format '{{json .Config.Labels}}' $container
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect a rehearsal container label."
        }
        $owner = ($labelsText | ConvertFrom-Json).'com.docker.compose.project'
        if ($owner -ne $projectName) {
            throw "Refusing cleanup because a container does not have the expected project label."
        }
    }
    foreach ($volume in $volumes) {
        $labelsText = & docker volume inspect --format '{{json .Labels}}' $volume
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect a rehearsal volume label."
        }
        $owner = ($labelsText | ConvertFrom-Json).'com.docker.compose.project'
        if ($owner -ne $projectName) {
            throw "Refusing cleanup because a volume does not have the expected project label."
        }
    }
    foreach ($network in $networks) {
        $labelsText = & docker network inspect --format '{{json .Labels}}' $network
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect a rehearsal network label."
        }
        $owner = ($labelsText | ConvertFrom-Json).'com.docker.compose.project'
        if ($owner -ne $projectName) {
            throw "Refusing cleanup because a network does not have the expected project label."
        }
    }
}

function ConvertFrom-ComposeJsonOutput([object[]]$OutputLines) {
    $jsonLines = @($OutputLines | ForEach-Object { [string]$_ } | Where-Object { $_.TrimStart().StartsWith("{") })
    if ($jsonLines.Count -eq 0) {
        throw "A rehearsal command did not return its expected JSON result."
    }
    return $jsonLines[-1] | ConvertFrom-Json
}

function Invoke-ComposeCaptured([string[]]$Arguments) {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & docker @composeArgs @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = @($output) }
}

function Write-SafeDiagnostics([object[]]$OutputLines) {
    foreach ($item in $OutputLines) {
        $line = [string]$item
        if ($line -match "Traceback|Error|Exception|ERROR|DETAIL|psycopg|Integrity") {
            $line = $line -replace '(?i)(postgres(?:ql)?://)[^@\s]+@', '$1[redacted]@'
            $line = $line -replace '(?i)(password|secret|token|access.?key|database_url)(\s*[:=]\s*)[^\s,;]+', '$1$2[redacted]'
            Write-Host $line
        }
    }
}

function Get-PendingCount([object]$Inventory) {
    $total = 0
    foreach ($item in $Inventory.PSObject.Properties) {
        $total += [int]$item.Value.pending
    }
    return $total
}

try {
    Assert-NoExistingProjectResources

    # Verify that the selected service graph cannot publish host ports.
    $configText = & docker @composeArgs config --format json
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to validate the isolated Compose configuration."
    }
    $config = ($configText -join "`n") | ConvertFrom-Json
    foreach ($serviceName in @("db", "seaweedfs", "seaweedfs-s3-proxy", "file-storage-maintenance")) {
        $servicePorts = $config.services.$serviceName.ports
        if ($null -ne $servicePorts -and @($servicePorts).Count -gt 0) {
            throw "Service '$serviceName' publishes a host port; refusing to start the rehearsal."
        }
    }

    $startedByThisScript = $true
    Invoke-Compose @("up", "--build", "--detach", "--wait", "--wait-timeout", "120", "db", "seaweedfs-s3-proxy")
    Invoke-Compose @("build", "backend", "file-storage-maintenance")
    Invoke-Compose @("run", "--rm", "-T", "--no-deps", "seaweedfs-init")
    Invoke-Compose @("run", "--rm", "-T", "--no-deps", "backend", "alembic", "upgrade", "head")

    $rehearsalEnvironment = "STORAGE_MIGRATION_REHEARSAL_PROJECT=$projectName"
    $fixtureRun = Invoke-ComposeCaptured @("run", "--rm", "-T", "--no-deps", "-e", $rehearsalEnvironment, "file-storage-maintenance", "python", "-m", "app.scripts.storage_migration_rehearsal_fixture", "create")
    if ($fixtureRun.ExitCode -ne 0) {
        Write-SafeDiagnostics $fixtureRun.Output
        throw "Unable to create synthetic migration rows in the isolated database."
    }
    $fixture = ConvertFrom-ComposeJsonOutput $fixtureRun.Output

    $firstRun = Invoke-ComposeCaptured @("run", "--rm", "-T", "--no-deps", "file-storage-maintenance", "python", "-m", "app.storage.maintenance_cli", "migrate", "--batch-size", "2")
    $firstResult = ConvertFrom-ComposeJsonOutput $firstRun.Output
    $first = $firstResult.report
    if ($firstRun.ExitCode -ne 1 -or $firstResult.operation -ne "migrate") {
        throw "The first migration pass did not report the expected controlled invalid-payload failure."
    }
    if ((Get-PendingCount $first.inventory) -ne 7 -or $first.migrated -ne 6 -or $first.failed -ne 1) {
        throw "The first pass did not inventory seven synthetic classes and migrate the six valid payloads."
    }
    if ((Get-PendingCount $first.remaining) -ne 1 -or $first.cutover_ready) {
        throw "The first pass did not leave exactly one repaired-payload gate open."
    }

    $repairRun = Invoke-ComposeCaptured @("run", "--rm", "-T", "--no-deps", "-e", $rehearsalEnvironment, "file-storage-maintenance", "python", "-m", "app.scripts.storage_migration_rehearsal_fixture", "repair", "--token", $fixture.token, "--gimelim-file-id", $fixture.gimelim_file_id)
    if ($repairRun.ExitCode -ne 0) {
        throw "Unable to repair the intentionally invalid synthetic payload."
    }
    [void](ConvertFrom-ComposeJsonOutput $repairRun.Output)

    $secondRun = Invoke-ComposeCaptured @("run", "--rm", "-T", "--no-deps", "file-storage-maintenance", "python", "-m", "app.storage.maintenance_cli", "migrate", "--batch-size", "2")
    $secondResult = ConvertFrom-ComposeJsonOutput $secondRun.Output
    $second = $secondResult.report
    if ($secondRun.ExitCode -ne 0 -or $secondResult.operation -ne "migrate") {
        throw "The resumed migration pass did not complete successfully."
    }
    if ($second.migrated -ne 1 -or $second.existing_verified -ne 7 -or $second.failed -ne 0) {
        throw "The resumed pass did not migrate one remaining file and verify all seven object references."
    }
    if ((Get-PendingCount $second.remaining) -ne 0 -or -not $second.cutover_ready) {
        throw "The resumed pass did not report zero pending files and cutover readiness."
    }

    $verifyRun = Invoke-ComposeCaptured @("run", "--rm", "-T", "--no-deps", "-e", $rehearsalEnvironment, "file-storage-maintenance", "python", "-m", "app.scripts.storage_migration_rehearsal_fixture", "verify", "--token", $fixture.token)
    if ($verifyRun.ExitCode -ne 0) {
        throw "Database-backed verification of all synthetic references failed."
    }
    $verifiedFixture = ConvertFrom-ComposeJsonOutput $verifyRun.Output

    [pscustomobject]@{
        project = $projectName
        first_pass = [pscustomobject]@{
            pending_before = Get-PendingCount $first.inventory
            migrated = $first.migrated
            failed_controlled_payload = $first.failed
            pending_after = Get-PendingCount $first.remaining
            cutover_ready = $first.cutover_ready
        }
        resumed_pass = [pscustomobject]@{
            migrated = $second.migrated
            existing_verified = $second.existing_verified
            failed = $second.failed
            pending_after = Get-PendingCount $second.remaining
            cutover_ready = $second.cutover_ready
        }
        database_fixture = $verifiedFixture
    } | ConvertTo-Json -Depth 5
}
finally {
    if ($startedByThisScript) {
        Assert-OwnedResourcesBeforeCleanup
        Invoke-Compose @("down", "--volumes", "--remove-orphans")
    }
}
