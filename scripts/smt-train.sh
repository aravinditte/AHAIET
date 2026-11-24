#!/usr/bin/env bash
# Train a Moses SMT model (Linux / WSL2). See docs/TRAINING.md for the
# Moses, GIZA++, and KenLM installation steps this script assumes.
# Usage: ./scripts/smt-train.sh biblical_hebrew [--allow-small] [--skip-tuning]
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
profile="${1:?usage: smt-train.sh <biblical_hebrew|biblical_aramaic> [extra train_smt.py flags]}"
shift || true
cd "$repo"
if [ -z "${MOSES_HOME:-}" ]; then
  echo "MOSES_HOME is not set. Install Moses (docs/TRAINING.md) and export MOSES_HOME, e.g.:"
  echo "  export MOSES_HOME=\$HOME/mosesdecoder"
fi
if ! command -v lmplz >/dev/null 2>&1 && [ -z "${KENLM_BIN:-}" ]; then
  echo "KenLM lmplz was not found (PATH or KENLM_BIN). The training script will stop with"
  echo "an actionable message; install KenLM first (docs/TRAINING.md)."
fi
python3 training/smt/train_smt.py --profile "$profile" "$@"
echo "Done. Check GET /api/models for the live artifact state."
