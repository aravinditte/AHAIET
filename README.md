# Ancient-Hebrew-Ancient-Aramaic-Image-to-English-Translator

A web application that translates Ancient Hebrew and Ancient Aramaic text captured from uploaded images into English.

**AHAIET** — upload a real image → preprocess → genuine local OCR → raw captured source text → correction → language profile → real local translation → complete English output → copy/export. Everything runs **offline and free** after provisioning: no paid API, no API key, no hosted translation/chatbot service, no runtime network inference, no telemetry.

> **Honest status:** the monorepo, backend API, upload validation/storage, database, and frontend are real. **OCR** is fully coded (Tesseract TSV with word confidences, preprocessing profiles) and its traineddata is downloaded, but it runs only where a Tesseract binary is installed — on the build machine the binary could not be provisioned, so OCR reports unavailable there (exact blocker in `docs/BUILD_STATE.md`). **Translation** returns a *verified reference* — the cited World English Bible text — when the corrected source exactly matches an imported corpus passage (morphhb/WLC Genesis + Daniel); text with no corpus match gets an honest unavailable response until a general local model is trained. No output is ever fabricated. See `docs/BUILD_STATE.md` and `docs/VERIFICATION.md`.

## Language profiles

- **Biblical Hebrew → English** — profile defined; corpus retrieval live for Genesis; general model not trained.
- **Biblical Aramaic → English** — a *separate* profile with its own corpus index (Daniel's Aramaic range) and morphology adapter. Biblical Aramaic is written in Hebrew script, so it is never classified as Hebrew from script alone.
- Future profiles (Old/Epigraphic Hebrew, Paleo-Hebrew, Qumran Hebrew, Old/Imperial Aramaic, Jewish Palestinian/Babylonian Aramaic, Classical Syriac) are listed by the API as `unsupported` until OCR models, corpora, and evaluation sets exist.

## Stack

Next.js + TypeScript + React + Tailwind CSS v4 frontend · Python 3.11+ FastAPI/Pydantic/Uvicorn backend, Pillow/NumPy (OpenCV optional) · SQLite (stdlib `sqlite3`, versioned migrations) · Tesseract baseline + Kraken adapter for OCR · Moses SMT + Marian NMT adapters for translation (the translation-model work). CPU-only must remain possible; WSL2/GPU/Docker are optional.

## Windows PowerShell quickstart (primary)

```powershell
# from the repository root, in PowerShell
.\scripts\setup-windows.ps1
.\scripts\verify-installation.ps1

# terminal 1 — backend on http://127.0.0.1:8000
.\scripts\start-backend.ps1

# terminal 2 — frontend on http://localhost:3000
.\scripts\start-frontend.ps1
```

Then open http://localhost:3000, upload a supported image (PNG/JPEG/TIFF/WEBP/BMP) and you will see its actual preview and the live capability states.

## OCR and corpus setup

```powershell
# Windows PowerShell — Tesseract binary + Hebrew traineddata
.\scripts\provision-ocr.ps1
# Reference corpus (morphhb/WLC + World English Bible) into SQLite
.\scripts\import-corpus.ps1
```
```bash
# bash equivalents
./scripts/provision-ocr.sh
./scripts/import-corpus.sh
```

With the corpus imported, translating a passage that matches Genesis or Daniel returns that edition's English with its citation and provenance; anything else reports that a trained general translation model is not yet available. `.\scripts\provision-models.ps1` only checks and reports model state; it downloads nothing silently.

## Training general translation models (Moses SMT + Marian NMT)

The full training infrastructure is in place; nothing has been trained yet, and the app says so honestly until a real run exports a model. Data first (per-profile parallel corpora with leakage checks and dataset cards), then training — Moses inside WSL2, Marian on CPU (GPU optional) — then the shared evaluation harness that scores every engine on the same held-out test split and records the winning engine per profile. One data fact shapes everything: under the recorded split strategy all Aramaic passages sit in the held-out test partition, so Aramaic currently has no training data and the pipelines refuse/report not-ready for that profile instead of improvising (details in `docs/TRAINING.md`).

```powershell
python training\datasets\prepare_parallel.py
.\scripts\smt-train.ps1 -Profile biblical_hebrew
.\scripts\nmt-train.ps1 -Profile biblical_hebrew
.\scripts\evaluate-translation.ps1 -Profile biblical_hebrew
```
```bash
python3 training/datasets/prepare_parallel.py
./scripts/smt-train.sh biblical_hebrew
./scripts/nmt-train.sh biblical_hebrew
./scripts/evaluate-translation.sh biblical_hebrew
```

Exported artifacts land in `artifacts/models/` (outside source control) with model cards; the backend then serves them through real subprocess adapters with per-profile selection, OOV warnings, and coverage reporting. See `docs/TRAINING.md` and `docs/MODEL_EVALUATION.md`.

Manual equivalent:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

cd ..\frontend
npm install
npm run typecheck
npm run build
npm run dev
```

## Layout

`frontend/` Next.js app · `backend/` FastAPI app (`app/api`, `app/core`, `app/schemas`, `app/services/{preprocessing,ocr,language,morphology,retrieval,translation,verification}`, `app/storage`) · `training/` dataset preparation, Moses SMT and Marian NMT orchestrators, OCR fixtures, and the shared translation evaluation harness (nothing trained yet) · `scripts/` PowerShell + bash setup/start/verify/provision/train/evaluate · `artifacts/manifests/` checksummed dataset & model manifests (binaries live outside source control) · `docs/` contract, build state, handoff, architecture, API, installation, limitations.

Continuity files — read these first in any new session: `docs/PROJECT_CONTRACT.md`, `docs/BUILD_STATE.md`, `docs/PHASE_HANDOFF.md`.

## License

MIT — see `LICENSE`. Corpus/model licences are tracked in `artifacts/manifests/` (WLC public domain, morphhb annotations CC BY 4.0, WEB public domain, tessdata Apache-2.0); corpus data files live outside source control in `artifacts/corpora/` (gitignored), with a six-passage fixture committed under `training/datasets/fixtures/` for tests.
