# Provision Kraken (historical-script OCR/HTR) — optional, WSL2-first.
# Kraken is a Python package (Apache-2.0). Its training/inference stack
# is Linux-first; on Windows the supported route is WSL2. This script
# checks prerequisites and prints the exact install commands — it does
# not install anything silently, and installing Kraken alone does NOT
# make any historical script supported (that additionally requires a
# trained checkpoint plus a measured evaluation record; see docs/OCR.md).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Write-Host "== Kraken provisioning check =="
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($wsl) {
    Write-Host "WSL2 is available. Install Kraken inside your WSL2 distribution:"
    Write-Host "  wsl bash -lc 'cd /mnt/c/path/to/ahaiet/backend && .venv/bin/pip install -e `".[kraken]`"'"
    Write-Host "  (adjust the path to this repository: $repo)"
    Write-Host "Or use the bash wrapper from inside WSL2: ./scripts/provision-kraken.sh"
} else {
    Write-Host "WSL2 was not found on PATH. Kraken on native Windows is not a supported route for this project."
    Write-Host "Enable WSL2 (wsl --install) and re-run, or work on a Linux machine."
}

Write-Host "`n== What provisioning Kraken does and does not do =="
Write-Host "Does: makes the ketos CLI and the Kraken Python API available so checkpoints can be trained and loaded."
Write-Host "Does NOT: provide any historical-script checkpoint or support claim. Check the live matrix any time:"
Write-Host "  Invoke-RestMethod http://127.0.0.1:8000/api/scripts"
