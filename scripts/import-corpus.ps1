# Download (if needed) and import the reference corpus:
# Open Scriptures morphhb (WLC, public domain; annotations CC BY 4.0)
# aligned with the World English Bible (public domain).
# Corpus data lands in artifacts\corpora (gitignored) and in the SQLite
# database; provenance and checksums are in artifacts\manifests\datasets.json.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repo "backend")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Backend venv not found. Run scripts\setup-windows.ps1 first."
    exit 1
}
& ".venv\Scripts\python.exe" -m app.corpus.import_morphhb --download --import-db
Write-Host "`nDone. Check GET /api/capabilities - corpus.status should be 'available'."
