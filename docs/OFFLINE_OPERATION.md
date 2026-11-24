# Offline operation

After dependency installation (pip/npm) and any explicit provisioning
steps, the application makes **no network calls**: no paid APIs, no
API keys, no hosted inference, no telemetry, no runtime model
downloads. This document states the setup/runtime boundary precisely
and how to prove it.

## The boundary

**Setup (network allowed, explicit commands only):**

- `pip install` / `npm install` of declared dependencies.
- `scripts/provision-ocr.ps1` / `.sh` — downloads the Tesseract
  Hebrew/English traineddata files into the repo-local `.tools`
  directory.
- `python -m app.corpus.import_morphhb --download` — downloads the
  public-domain corpus sources (morphhb/WLC XML, World English Bible)
  and imports them into the local SQLite database. Without
  `--download` it works from already-downloaded local files.
- `scripts/provision-models.ps1` performs checks only and downloads
  nothing. Training toolchains (Moses, Marian) are installed by the
  developer per docs/TRAINING.md.

**Runtime (no network, ever):**

- The frontend talks only to the local backend
  (`NEXT_PUBLIC_API_BASE`, default `http://127.0.0.1:8000`). It loads
  no remote fonts, no CDN assets, and no analytics: the Hebrew font
  stack is system/local (`"SBL Hebrew", "Ezra SIL", "David",
  "Times New Roman", serif` in `frontend/src/app/globals.css`), and
  `frontend/next.config.mjs` contains nothing that fetches at
  runtime.
- The backend serves OCR (Tesseract/Kraken), retrieval, morphology,
  verification, and translation (Moses/Marian) from local processes,
  local files, and the local SQLite database.
- There are no API keys anywhere in the system — nothing to leak and
  nothing to bill.

## Proof 1 — static self-check

```powershell
cd backend
python -m app.offline_check          # human-readable report
python -m app.offline_check --json   # machine-readable
```

This scans every Python file in the backend package for outbound-call
constructs (`urllib.request`/`urlopen`, `requests`, `httpx` clients,
raw `socket`, `http.client`). It exits non-zero if any are found
outside the allowlist. The allowlist is exactly:

- `app/corpus/import_morphhb.py` — the setup-only corpus importer
  (network only under its `--download` flag), and
- `app/offline_check.py` — the scanner itself (it matches its own
  pattern strings).

## Proof 2 — socket-blocked integration tests

`backend/tests/test_offline.py` monkeypatches
`socket.socket.connect`/`connect_ex` and `socket.create_connection`
to raise, then exercises the real request paths through the in-process
test client: health, capabilities, a verified-reference translation
from the locally imported fixture corpus, and morphology. If any
runtime path needed the network, these tests would fail.

## Proof 3 — one-command script

```powershell
scripts\verify-offline.ps1    # Windows
./scripts/verify-offline.sh   # bash
```

Runs both proofs above. The script needs no administrator rights and
changes no system settings. For a stronger manual proof, its header
documents the optional Windows Defender Firewall outbound-block steps
(block the backend's `python.exe`, repeat the UI flow, delete the
rule) — the script prints the steps; it does not execute them.

## Notes

- `frontend/next.config.mjs` is minimal (`reactStrictMode` only): no
  remote image domains, no rewrites to external services, nothing
  that fetches at runtime.
- Blocking the machine's network entirely is also safe for runtime
  use: every runtime feature works from local files and processes.

## Opt-in real-pipeline acceptance test (AHAIET-007/030)

`backend/tests/test_real_pipeline_acceptance.py` is the end-to-end
proof for this document: with sockets blocked, it runs image upload ->
OCR -> correction -> translation through the real API and asserts the
lineage fields survive. It is marked `model_required` and **skips with
the exact missing prerequisite** (Tesseract binary, heb traineddata, a
resolved translation artifact or imported corpus) when the machine is
not provisioned. The run itself is the developer's; until it has been
run and recorded, the `offline_benchmark_passed` provisioning state
(docs/PROVISIONING.md) is not claimed.
