# Train a Moses SMT model inside WSL2 (Windows wrapper).
#
# Moses training is a WSL2 workflow (docs/TRAINING.md has the exact apt
# installs for Moses, GIZA++, and KenLM inside the WSL2 distribution).
# This wrapper checks that WSL2 exists, converts the repository path,
# and runs training/smt/train_smt.py inside WSL2. Runtime inference does
# NOT need WSL2 — the backend calls a locally installed moses binary.
#
# Usage:
#   .\scripts\smt-train.ps1 -Profile biblical_hebrew
#   .\scripts\smt-train.ps1 -Profile biblical_aramaic -AllowSmall
param(
    [Parameter(Mandatory = $true)][ValidateSet("biblical_hebrew", "biblical_aramaic")]
    [string]$Profile,
    [switch]$AllowSmall,
    [switch]$SkipTuning
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wsl) {
    Write-Host "WSL2 was not found on this machine, so Moses training cannot run."
    Write-Host "Install it (admin PowerShell):  wsl --install -d Ubuntu"
    Write-Host "Then follow the Moses/GIZA++/KenLM setup in docs/TRAINING.md and re-run this script."
    exit 1
}
$distros = wsl --list --quiet
if (-not $distros) {
    Write-Host "WSL2 is installed but no Linux distribution is registered."
    Write-Host "Install one:  wsl --install -d Ubuntu   (then set up Moses per docs/TRAINING.md)"
    exit 1
}

$extra = ""
if ($AllowSmall) { $extra += " --allow-small" }
if ($SkipTuning) { $extra += " --skip-tuning" }
$cmd = "cd `$(wslpath -a '$repo') && python3 training/smt/train_smt.py --profile $Profile$extra"
Write-Host "Running inside WSL2: $cmd"
wsl bash -lc $cmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "SMT training stopped with exit code $LASTEXITCODE (see the message above and training/smt/work/*/train.log)."
    exit $LASTEXITCODE
}
Write-Host "Done. The exported artifact and model card are under artifacts/models/smt/; check GET /api/models for the live artifact state."
