# Provision the Tesseract OCR engine + Hebrew traineddata (Windows).
# This script performs the documented downloads/installs explicitly -
# nothing is fetched silently by the application at runtime.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $repo ".tools"
$tessdata = Join-Path $tools "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null

Write-Host "== Tesseract binary =="
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if ($tess) {
    Write-Host "Found on PATH: $($tess.Source)"
    tesseract --version
} else {
    Write-Host "Tesseract is NOT on PATH."
    Write-Host "Install it with winget (UB Mannheim build, includes many languages):"
    Write-Host "  winget install --id UB-Mannheim.TesseractOCR"
    Write-Host "Then re-run this script. During installation, tick the Hebrew language data if offered."
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

Write-Host "`n== Backend environment for this session =="
Write-Host "`$env:TESSDATA_PREFIX = `"$tessdata`""
Write-Host "Set AHAIET_TESSERACT_CMD if tesseract.exe is not on PATH, e.g.:"
Write-Host "`$env:AHAIET_TESSERACT_CMD = `"C:\Program Files\Tesseract-OCR\tesseract.exe`""
Write-Host "Then start the backend and check GET /api/capabilities - ocr.status should be 'available'."
