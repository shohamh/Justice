$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'e2e.ps1'
$validUrl = 'postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e'

& $runner -ValidateOnly -E2eDatabaseUrl $validUrl
if ($LASTEXITCODE -ne 0) {
    throw 'The E2E runner rejected an explicitly named E2E database in validate-only mode.'
}

& $runner -ValidateOnly -E2eDatabaseUrl 'postgresql+psycopg://app:app_pw@localhost:5432/justice'
if ($LASTEXITCODE -eq 0) {
    throw 'The E2E runner accepted the regular development database.'
}
