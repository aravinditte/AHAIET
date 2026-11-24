# Browser end-to-end tests (Playwright)

These specs drive the real UI through the translator flows (upload a
fixture page image, run OCR, correct, translate, copy, export) for a
Hebrew passage and an Aramaic passage.

**They are not part of always-on CI** (`.github/workflows/ci.yml` runs
typecheck, vitest, and the production build only). They need a fully
provisioned local environment, because they exercise the real OCR
engine and the real corpus:

## Prerequisites

1. Backend dependencies installed and the reference corpus imported:
   ```powershell
   cd backend; .\.venv\Scripts\Activate.ps1
   python -m app.corpus.import_morphhb --download --import-db
   ```
2. Tesseract provisioned (binary + Hebrew traineddata):
   `scripts\provision-ocr.ps1` (Windows) or `scripts/provision-ocr.sh`.
3. Fixture images generated:
   ```powershell
   python training\ocr\generate_fixtures.py
   ```
   (produces `training/ocr/fixtures/genesis-1-1.png` and
   `daniel-2-4.png`; a spec skips with the missing file named when its
   fixture is absent).
4. Playwright and its browser installed once:
   ```powershell
   cd frontend
   npm install
   npx playwright install chromium
   ```

## Run

Start the backend in one terminal:

```powershell
cd backend; .\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --port 8000
```

Then, in another terminal:

```powershell
cd frontend
npm run test:e2e
```

The Playwright config starts the frontend dev server itself
(`webServer` in `playwright.config.ts`, reusing an already-running
one). Set `AHAIET_E2E_BASE_URL` to point at a different frontend URL.

Bash equivalents: activate `.venv/bin/activate`, use
`scripts/provision-ocr.sh`, and the same `npm run test:e2e`.

## What the specs assert

- The Hebrew spec uploads the Genesis 1:1 fixture, runs OCR, checks
  the corrected editor is prefilled from the captured text, translates,
  and requires the displayed English to be the corpus reference
  translation for Genesis 1:1 (read from the committed fixture file,
  not hard-coded). It then copies the English via the real button
  (clipboard permissions are granted in the config) and downloads the
  JSON export.
- The Aramaic spec selects the Biblical Aramaic profile explicitly,
  uploads the Daniel 2:4 fixture, and requires either the verified
  translation panel or the backend's explicit error state — never a
  result produced under the Hebrew profile.
- If OCR is not provisioned, the specs skip with the prerequisite
  named instead of failing on an empty transcription.
