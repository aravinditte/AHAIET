# Provision the Tesseract OCR engine + Hebrew traineddata (Windows).
# AHAIET-032: with -Install this script actually installs Tesseract
# via winget, verifies `tesseract --list-langs` contains heb, runs a
# smoke OCR on the committed fixture image when one exists, and
# PERSISTS the settings into ahaiet.local.env at the repo root, which
# scripts/start-backend.ps1 loads on every start. Without -Install it
# only reports/downloads traineddata, as before.
param([switch]$Install)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $repo ".tools"
$tessdata = Join-Path $tools "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null

Write-Host "== Tesseract binary =="
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tess -and $Install) {
    Write-Host "Installing Tesseract via winget (UB Mannheim build)..."
    winget install --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
    $tess = Get-Command tesseract -ErrorAction SilentlyContinue
    if (-not $tess) {
        $candidate = "C:\Program Files\Tesseract-OCR\tesseract.exe"
        if (Test-Path $candidate) { $tess = Get-Item $candidate }
    }
}
if ($tess) {
    $tessPath = if ($tess.Source) { $tess.Source } else { $tess.FullName }
    Write-Host "Found: $tessPath"
    & $tessPath --version
} else {
    Write-Host "Tesseract is NOT installed. Re-run with -Install to install it via winget:"
    Write-Host "  .\scripts\provision-ocr.ps1 -Install"
    Write-Host "or install manually: winget install --id UB-Mannheim.TesseractOCR"
}

Write-Host "`n== Hebrew + English traineddata (Apache-2.0, tesseract-ocr/tessdata) =="
foreach ($lang in @("heb", "eng")) {
    $dest = Join-Path $tessdata "$lang.traineddata"
    if (Test-Path $dest) {
        Write-Host "$lang.traineddata already present: $dest"
    } else {
        $url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$lang.traineddata"
        Write-Host "Downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $dest
    }
    Get-FileHash $dest -Algorithm SHA256 | ForEach-Object { Write-Host "  sha256 $($_.Hash.ToLower())  $($_.Path)" }
}

if ($tess) {
    $tessPath = if ($tess.Source) { $tess.Source } else { $tess.FullName }
    Write-Host "`n== Verification: tesseract --list-langs =="
    $env:TESSDATA_PREFIX = $tessdata
    $langs = & $tessPath --list-langs 2>&1
    $langs | ForEach-Object { Write-Host "  $_" }
    if ($langs -notmatch "heb") {
        Write-Host "ERROR: 'heb' is not in the language list; OCR for the Hebrew-script profiles will not run."
        exit 1
    }
    Write-Host "heb language data verified."

    Write-Host "`n== Smoke OCR on the committed fixture (when present) =="
    $fixture = Join-Path $repo "training\ocr\fixtures\genesis_1_1_hebrew.png"
    if (Test-Path $fixture) {
        $smoke = & $tessPath $fixture stdout -l heb --psm 6 2>&1
        Write-Host "smoke OCR output (first 120 chars): $($smoke.Substring(0, [Math]::Min(120, $smoke.Length)))"
    } else {
        Write-Host "fixture image not generated yet (training\ocr\generate_fixtures.py); smoke OCR skipped."
    }

    Write-Host "`n== Persisting settings to ahaiet.local.env =="
    $envFile = Join-Path $repo "ahaiet.local.env"
    @(
        "# Written by scripts/provision-ocr.ps1 - loaded by scripts/start-backend.ps1"
        "TESSDATA_PREFIX=$tessdata"
        "AHAIET_TESSERACT_CMD=$tessPath"
    ) | Set-Content -Path $envFile -Encoding UTF8
    Write-Host "wrote $envFile"
}
Write-Host "`nThen start the backend (.\scripts\start-backend.ps1) and check GET /api/capabilities - ocr.tesseract.usable should be true."
