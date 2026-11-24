# Train (or fine-tune) a Marian NMT model (Windows wrapper).
#
# Marian runs natively on Windows or inside WSL2; this wrapper uses the
# Python on PATH and calls training/nmt/train_nmt.py. The data gate
# applies: a profile below the minimum training-pair count gets a
# not-ready report instead of a training run (expected today for
# Biblical Aramaic — see the report under artifacts/models/nmt/).
#
# Usage:
#   .\scripts\nmt-train.ps1 -Profile biblical_hebrew
#   .\scripts\nmt-train.ps1 -Profile biblical_hebrew -Pretrained C:\models\opus-mt\model.npz
param(
    [Parameter(Mandatory = $true)][ValidateSet("biblical_hebrew", "biblical_aramaic")]
    [string]$Profile,
    [string]$Pretrained = "",
    [ValidateSet("cpu", "gpu")][string]$Variant = "cpu",
    [int]$MinTrainPairs = 500
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python was not found on PATH. Install Python 3.11+ and re-run."
    exit 1
}
if (-not (Get-Command marian -ErrorAction SilentlyContinue) -and -not $env:MARIAN_BIN) {
    Write-Host "The marian training binary was not found (PATH or MARIAN_BIN)."
    Write-Host "The orchestrator will still run the data gate and vocabulary steps, then stop"
    Write-Host "with an actionable message. Install Marian per docs/TRAINING.md to train."
}
$argsList = @("training/nmt/train_nmt.py", "--profile", $Profile,
              "--config-variant", $Variant, "--min-train-pairs", $MinTrainPairs)
if ($Pretrained) { $argsList += @("--pretrained", $Pretrained) }
& python @argsList
if ($LASTEXITCODE -eq 3) {
    Write-Host "Not ready: the data gate or a prerequisite stopped the run (see the report/message above). This is an expected outcome, not a crash."
    exit 3
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "NMT training stopped with exit code $LASTEXITCODE (see training/nmt/work/*/train.log)."
    exit $LASTEXITCODE
}
Write-Host "Done. The exported artifact and model card are under artifacts/models/nmt/; check GET /api/models."
