# Verify offline operation: run the static offline self-check and the
# socket-blocked offline integration tests. No administrator rights are
# needed and this script changes no system settings.
#
# For a stronger, manual proof on Windows you can additionally block
# the backend process in Windows Defender Firewall and repeat the
# manual flow (upload -> OCR -> translate) in the UI:
#   1. Open "Windows Defender Firewall with Advanced Security".
#   2. Outbound Rules -> New Rule -> Program -> select the backend's
#      python.exe (backend\.venv\Scripts\python.exe) -> Block the
#      connection -> all profiles -> name it e.g. "AHAIET offline test".
#   3. Run the app and exercise it; then delete the rule afterwards.
# This script prints those steps; it does not execute them.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repo "backend\.venv\Scripts\python.exe"
if (Test-Path $venvPython) { $python = $venvPython } else { $python = "python" }

Write-Host "== Static offline self-check (backend package scan) =="
Push-Location (Join-Path $repo "backend")
try {
    & $python -m app.offline_check
    if ($LASTEXITCODE -ne 0) { throw "offline_check reported runtime findings" }
    Write-Host "`n== Offline integration tests (sockets blocked) =="
    & $python -m pytest tests\test_offline.py -q
    if ($LASTEXITCODE -ne 0) { throw "offline tests failed" }
} finally { Pop-Location }

Write-Host "`nOptional manual firewall proof (not executed): see the header of this script."
