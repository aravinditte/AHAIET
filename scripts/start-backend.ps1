$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# Load persisted local settings (written by scripts/provision-ocr.ps1:
# TESSDATA_PREFIX, AHAIET_TESSERACT_CMD) when present (AHAIET-032).
$envFile = Join-Path $Root "ahaiet.local.env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*([^#=]+)=(.*)$") {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
    Write-Host "loaded $envFile"
}
Set-Location "$Root\backend"
# Invoke the venv interpreter directly (no Activate.ps1, so execution
# policy cannot block startup).
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
