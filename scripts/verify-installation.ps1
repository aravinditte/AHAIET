# Checks (does not install or download anything): Python, Node, Tesseract, backend tests, capabilities.
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Python:"; py -3.11 --version
Write-Host "Node:"; node --version
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if ($tess) { Write-Host "Tesseract: $($tess.Source)"; tesseract --version } else { Write-Host "Tesseract: NOT FOUND - OCR will report unavailable (see docs\OCR.md)" }
Set-Location "$Root\backend"
.\.venv\Scripts\Activate.ps1
python -m pytest -q
Write-Host "Start the backend (scripts\start-backend.ps1), then check http://127.0.0.1:8000/api/capabilities"
Set-Location $Root
