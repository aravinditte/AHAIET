# AHAIET - Windows setup (PowerShell). Run from the repository root.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "== Backend =="
Set-Location "$Root\backend"
# AHAIET-032: accept any Python 3.11+ via the py launcher fallback
# chain, instead of requiring one exact minor version.
$py = $null
foreach ($args in @("-3.13", "-3.12", "-3.11", "-3")) {
    try { & py $args -c "import sys; assert sys.version_info >= (3, 11)"; if ($LASTEXITCODE -eq 0) { $py = $args; break } } catch {}
}
if (-not $py) { throw "No Python 3.11+ found via the py launcher. Install Python 3.11 or newer from python.org." }
Write-Host "using py $py"
& py $py -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
Write-Host "== Frontend =="
Set-Location "$Root\frontend"
npm ci
Set-Location $Root
Write-Host "Setup complete. Next: .\scripts\verify-installation.ps1"
