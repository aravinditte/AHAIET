#!/usr/bin/env bash
# Provision Kraken (historical-script OCR/HTR) into the backend venv.
# Linux / WSL2. Installing the package does NOT make any historical
# script supported: support additionally requires a trained checkpoint
# and a measured evaluation record (see docs/OCR.md).
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo/backend"
if [ ! -x ".venv/bin/python" ]; then
  echo "Backend venv not found. Create it: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  exit 1
fi
.venv/bin/pip install -e ".[kraken]"
.venv/bin/python -c "import importlib.metadata; print('kraken', importlib.metadata.version('kraken'))"
command -v ketos >/dev/null && ketos --version || echo "ketos CLI not on PATH (the Python API may still be usable)"
echo "Done. Check GET /api/scripts for the live script support matrix."
