# AHAIET - Windows setup (PowerShell). Run from the repository root.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "== Backend =="
Set-Location "$Root\backend"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Write-Host "== Frontend =="
Set-Location "$Root\frontend"
npm install
Set-Location $Root
Write-Host "Setup complete. Next: .\scripts\verify-installation.ps1"
