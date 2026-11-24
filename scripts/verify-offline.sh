#!/usr/bin/env bash
# Verify offline operation: run the static offline self-check and the
# socket-blocked offline integration tests. No root needed; this script
# changes no system settings.
#
# For a stronger, manual proof you can additionally run the backend in
# a network namespace with no external route (Linux: `unshare -n`, which
# also removes loopback unless you raise it) or block outbound traffic
# for the backend process in your firewall, then repeat the manual flow
# (upload -> OCR -> translate) in the UI. Those steps are documented in
# docs/OFFLINE_OPERATION.md; this script does not execute them.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$repo/backend/.venv/bin/python" ]; then python="$repo/backend/.venv/bin/python"; else python="python3"; fi

echo "== Static offline self-check (backend package scan) =="
(cd "$repo/backend" && "$python" -m app.offline_check)
echo
echo "== Offline integration tests (sockets blocked) =="
(cd "$repo/backend" && "$python" -m pytest tests/test_offline.py -q)
