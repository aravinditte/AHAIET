# AHAIET - model provisioning CHECK ONLY.
# This script downloads nothing and trains nothing. It reports what is present/missing
# and prints the manual steps. Provisioning is an explicit, separate, human-run action.
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "== OCR =="
$tess = Get-Command tesseract -ErrorAction SilentlyContinue
if ($tess) { Write-Host "tesseract: FOUND at $($tess.Source)"; tesseract --list-langs } else { Write-Host "tesseract: MISSING. Install from https://github.com/UB-Mannheim/tesseract/wiki and add Hebrew (heb) traineddata." }
Write-Host "Kraken: check with  python -c ""import kraken""  (not installed by default; no model is provisioned in Part 1)"
Write-Host "== Translation models =="
Get-Content "$Root\artifacts\manifests\models.json"
Write-Host "All translation entries are expected to be status=not_provisioned in Part 1. A model counts as provisioned only when a real trained artifact exists on disk, its checksum is recorded in models.json, and it has been evaluated (docs\MODEL_EVALUATION.md)."
Write-Host "== Datasets =="
Get-Content "$Root\artifacts\manifests\datasets.json"
Write-Host "Dataset list is intentionally empty in Part 1. See docs\DATASETS.md for licensing/provenance rules before adding any corpus."
