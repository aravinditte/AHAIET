#!/usr/bin/env bash
# Run the shared translation evaluation harness for one profile
# (Linux / WSL2 / macOS). See docs/MODEL_EVALUATION.md.
# Usage: ./scripts/evaluate-translation.sh biblical_hebrew [--no-write-selection]
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
profile="${1:?usage: evaluate-translation.sh <biblical_hebrew|biblical_aramaic> [--no-write-selection]}"
shift || true
cd "$repo"
python3 training/evaluation/evaluate_translation.py --profile "$profile" "$@"
echo "Reports: artifacts/benchmarks/$profile-translation-eval.json and .md"
echo "Remember: retrieval coverage on the test split is an upper-bound figure (the test verses come from the same corpus as the retrieval index)."
