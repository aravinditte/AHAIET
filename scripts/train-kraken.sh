#!/usr/bin/env bash
# Train a Kraken historical-script recognition checkpoint (Linux / WSL2).
# Usage: ./scripts/train-kraken.sh <script-profile> <data-dir> [base-checkpoint]
# The data directory must contain provenance.txt and train/ line pairs
# (see training/ocr/train_kraken.py). Exporting a checkpoint does not by
# itself make the profile supported — run the HTR evaluation afterwards.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
profile="${1:?usage: train-kraken.sh <script-profile> <data-dir> [base-checkpoint]}"
data_dir="${2:?usage: train-kraken.sh <script-profile> <data-dir> [base-checkpoint]}"
base_args=()
if [ -n "${3:-}" ]; then base_args=(--base-checkpoint "$3"); fi
cd "$repo"
if [ ! -x "backend/.venv/bin/python" ]; then
  echo "Backend venv not found. Create it: python3 -m venv .venv && .venv/bin/pip install -e '.[dev,kraken]'"
  exit 1
fi
backend/.venv/bin/python training/ocr/train_kraken.py \
  --profile "$profile" --data-dir "$data_dir" "${base_args[@]}"
