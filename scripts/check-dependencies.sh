#!/usr/bin/env bash
# Report installed dependency versions vs the bounds declared in
# backend/pyproject.toml and training/requirements.txt.
# Uses only the local environment's package metadata - no network calls.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$repo/backend/.venv/bin/python" ]; then python="$repo/backend/.venv/bin/python"; else python="python3"; fi
exec "$python" "$repo/scripts/check_dependencies.py" "$@"
