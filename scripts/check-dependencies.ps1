# Report installed dependency versions vs the bounds declared in
# backend/pyproject.toml and training/requirements.txt.
# Uses only the local environment's package metadata - no network calls.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repo "backend\.venv\Scripts\python.exe"
if (Test-Path $venvPython) { $python = $venvPython } else { $python = "python" }
& $python (Join-Path $repo "scripts\check_dependencies.py") @args
exit $LASTEXITCODE
