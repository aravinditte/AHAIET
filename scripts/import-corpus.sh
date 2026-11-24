#!/usr/bin/env bash
# Download (if needed) and import the reference corpus (morphhb/WLC +
# World English Bible). See scripts/import-corpus.ps1 for the Windows
# equivalent and artifacts/manifests/datasets.json for provenance.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo/backend"
if [ ! -x ".venv/bin/python" ]; then
  echo "Backend venv not found. Create it: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  exit 1
fi
.venv/bin/python -m app.corpus.import_morphhb --download --import-db
echo "Done. Check GET /api/capabilities - corpus.status should be 'available'."
