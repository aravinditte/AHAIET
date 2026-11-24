# Train a Kraken historical-script recognition checkpoint (Windows wrapper).
# Kraken training is Linux-first, so on Windows this wrapper runs the
# orchestrator inside WSL2. The native-Windows alternative is to run the
# same command on a Linux machine.
#   .\scripts\train-kraken.ps1 -Profile paleo_hebrew -DataDir D:\kraken-data\paleo
param(
    [Parameter(Mandatory = $true)][string]$Profile,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$BaseCheckpoint = "",
    [int]$Epochs = 50
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wsl) {
    Write-Host "WSL2 is required for Kraken training on Windows (wsl --install), or run scripts/train-kraken.sh on Linux."
    exit 1
}
$wslRepo = (wsl wslpath -a "$repo").Trim()
$wslData = (wsl wslpath -a "$DataDir").Trim()
$base = ""
if ($BaseCheckpoint) {
    $wslBase = (wsl wslpath -a "$BaseCheckpoint").Trim()
    $base = "--base-checkpoint $wslBase"
}
$cmd = "cd $wslRepo && backend/.venv/bin/python training/ocr/train_kraken.py --profile $Profile --data-dir $wslData --epochs $Epochs $base"
Write-Host "Running in WSL2: $cmd"
wsl bash -lc $cmd
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Checkpoint exported under artifacts/models/kraken/$Profile. Support still requires a measured evaluation:"
Write-Host "  python training/evaluation/evaluate_htr.py --profile $Profile --checkpoint artifacts/models/kraken/$Profile/model.mlmodel --test-dir <labelled-test-dir>"
