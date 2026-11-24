# Troubleshooting

Symptom → likely cause → fix. Everything here is local; no step needs
an account or an API key.

## OCR returns `ocr_unavailable` / "Tesseract is not available"

- **Cause:** the Tesseract binary is not installed or not on `PATH`
  (or `AHAIET_TESSERACT_CMD` points somewhere wrong).
- **Fix:** install Tesseract (Windows: the UB-Mannheim build linked
  from docs/OCR.md), then confirm from the same terminal the backend
  runs in:
  ```powershell
  tesseract --version
  ```
  Or set `AHAIET_TESSERACT_CMD` to the full path of `tesseract.exe`.

## OCR runs but finds no Hebrew / language data missing

- **Cause:** the Hebrew traineddata (`heb.traineddata`) is not where
  Tesseract looks — `TESSDATA_PREFIX` unset, or provisioning not run.
- **Fix:**
  ```powershell
  scripts\provision-ocr.ps1        # downloads heb+eng into .tools\tessdata
  $env:TESSDATA_PREFIX = "$PWD\.tools\tessdata"   # same terminal as the backend
  ```
  Check readiness in the UI's readiness panel or
  `GET /api/capabilities` → `ocr.tesseract.traineddata`.

## Translation always says no corpus match / morphology says `corpus_unavailable`

- **Cause:** the reference corpus was never imported into the SQLite
  database the backend is using (or `AHAIET_DB_PATH` points at a
  different, empty database).
- **Fix:**
  ```powershell
  cd backend
  python -m app.corpus.import_morphhb --download --import-db
  ```
  Then `GET /api/capabilities` should report `corpus.status:
  available` with a passage count.

## A trained model shows as unavailable although files exist

- **Cause:** the artifact is incomplete for its engine — e.g. a Moses
  directory without its language model, a Marian checkpoint without
  its vocabulary, a missing `model_card.json`, or a checksum that does
  not match the model card. The backend lists exactly which component
  is missing instead of guessing.
- **Fix:** compare the artifact directory against the completeness
  rules in docs/TRAINING.md ("Model cards and artifact resolution")
  and re-export or re-train; `GET /api/models` shows the per-model
  state and evaluation state.

## Aramaic cannot be trained / evaluates as unavailable

- **Cause:** this is a data fact, not a bug. Under the recorded
  dataset split (Genesis 1–25 train, Genesis 26–50 validation, Daniel
  test), **Biblical Aramaic has zero training pairs** — every Aramaic
  verse in the corpus is in Daniel, which is the test partition. The
  training pipeline refuses to train on an empty training set and
  reports exactly that.
- **Fix options (a data decision, not a code change):** import the
  Aramaic portions of Ezra into the corpus so Aramaic has training
  material, or deliberately revise the split in
  `training/datasets/prepare_parallel.py` and record the change in
  the dataset card. Until then, Aramaic translation is served by
  verified corpus retrieval only.

## Kraken reports an incompatible version or `ketos` not found

- **Cause:** the `ketos` CLI (Kraken) is not installed, or its version
  is outside the supported bound declared in
  `backend/pyproject.toml` / `training/requirements.txt`.
- **Fix:** install a Kraken within the declared bound
  (`pip install "kraken>=4.3,<6"`), confirm `ketos --version`, or set
  `AHAIET_KRAKEN_CMD`. Historical-script recognition additionally
  needs a trained checkpoint **and** a measured evaluation record
  before the support matrix will call a script supported — a missing
  checkpoint is reported as `not_provisioned`, not worked around.

## Port already in use (8000 or 3000)

- **Cause:** another process (often an earlier backend/frontend you
  left running) holds the port.
- **Fix:** find and stop it, or choose another port and keep the two
  sides consistent:
  ```powershell
  # who holds 8000?
  Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
  # backend on a different port + matching frontend API base
  python -m uvicorn app.main:app --port 8001
  $env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:8001"   # before npm run dev
  ```

## PowerShell refuses to run scripts ("running scripts is disabled")

- **Cause:** the default execution policy blocks `.ps1` files,
  including virtualenv activation.
- **Fix (current window only, no admin, no lasting change):**
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  ```
  Or avoid activation entirely and call the venv interpreter
  directly: `backend\.venv\Scripts\python.exe -m uvicorn app.main:app`.

## The UI loads but every action errors

- **Cause:** the backend is not running, or the frontend's API base
  points elsewhere.
- **Fix:** open `http://127.0.0.1:8000/api/health` directly — it must
  return `{"status":"ok", ...}`. If the backend runs on another port,
  set `NEXT_PUBLIC_API_BASE` before starting the frontend (Next.js
  reads it at startup/build time, so restart the frontend after
  changing it). CORS errors in the browser console mean the page
  origin is not in `AHAIET_CORS_ORIGINS` (defaults cover
  `localhost:3000` and `127.0.0.1:3000` only).

## `429 rate_limited` during heavy manual testing

- **Cause:** the per-client rate limits (a security guardrail) were
  hit — defaults are 30 uploads/OCR/process and 60 translations per
  minute per client.
- **Fix:** wait for the `Retry-After` window, or raise the specific
  limit for your local session, e.g.
  `AHAIET_RATE_LIMIT_TRANSLATE_PER_MIN=600`. Do not raise them on a
  shared deployment.
