$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

& $python -m pytest tests app/services/tests app/services/hr/tests app/tests @args
exit $LASTEXITCODE
