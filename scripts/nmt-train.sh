#!/usr/bin/env bash
# Train (or fine-tune) a Marian NMT model (Linux / WSL2 / macOS).
# Usage: ./scripts/nmt-train.sh biblical_hebrew [--config-variant gpu] [--pretrained PATH]
# The data gate applies: below the minimum training-pair count the
# orchestrator writes a not-ready report and exits 3 (expected today
# for Biblical Aramaic).
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
profile="${1:?usage: nmt-train.sh <biblical_hebrew|biblical_aramaic> [extra train_nmt.py flags]}"
shift || true
cd "$repo"
if ! command -v marian >/dev/null 2>&1 && [ -z "${MARIAN_BIN:-}" ]; then
  echo "The marian binary was not found (PATH or MARIAN_BIN). The orchestrator will still"
  echo "run the data gate and vocabulary steps, then stop with an actionable message."
  echo "Install Marian first (docs/TRAINING.md) to actually train."
fi
python3 training/nmt/train_nmt.py --profile "$profile" "$@"
echo "Done. Check GET /api/models for the live artifact state."
