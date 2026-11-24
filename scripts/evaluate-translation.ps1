# Run the shared translation evaluation harness for one profile.
#
# Every available engine is scored over the SAME held-out test split;
# unavailable engines are reported with their reason, never zero-filled.
# With selection writing enabled (default) the winning trained engine is
# recorded into its model card and the models manifest.
#
# Usage:
#   .\scripts\evaluate-translation.ps1 -Profile biblical_hebrew
#   .\scripts\evaluate-translation.ps1 -Profile biblical_aramaic -NoWriteSelection
param(
    [Parameter(Mandatory = $true)][ValidateSet("biblical_hebrew", "biblical_aramaic")]
    [string]$Profile,
    [switch]$NoWriteSelection
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python was not found on PATH. Install Python 3.11+ and re-run."
    exit 1
}
$argsList = @("training/evaluation/evaluate_translation.py", "--profile", $Profile)
if ($NoWriteSelection) { $argsList += "--no-write-selection" }
& python @argsList
if ($LASTEXITCODE -ne 0) {
    Write-Host "Evaluation stopped with exit code $LASTEXITCODE (see the message above)."
    exit $LASTEXITCODE
}
Write-Host "Reports: artifacts/benchmarks/$Profile-translation-eval.json and .md"
Write-Host "Remember: retrieval coverage on the test split is an upper-bound figure (the test verses come from the same corpus as the retrieval index)."
