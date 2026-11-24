# Ancient-Hebrew-Ancient-Aramaic-Image-to-English-Translator

A web application that translates Ancient Hebrew and Ancient Aramaic text captured from uploaded images into English.

**AHAIET** — upload a real image → preprocess → genuine local OCR → raw captured source text → correction → language profile → real local translation → complete English output → copy/export. Everything runs **offline and free** after provisioning: no paid API, no API key, no hosted translation/chatbot service, no runtime network inference, no telemetry.

> **Honest status (Part 1 of 5 — Foundation):** the monorepo, backend API, upload validation/storage, database, and frontend are real and tested. **OCR and translation are NOT ready yet**: no Tesseract binary, Kraken model, Moses SMT model, or Marian NMT model is provisioned in this repository, so `/api/ocr`, `/api/translate`, and `/api/process` return explicit `503` unavailable responses with actionable reasons instead of fabricated text. See `docs/BUILD_STATE.md`.

## Language profiles

- **Biblical Hebrew → English** — profile defined; models not provisioned.
- **Biblical Aramaic → English** — a *separate* profile. Biblical Aramaic is written in Hebrew script, so it is never classified as Hebrew from script alone.
- Future profiles (Old/Epigraphic Hebrew, Paleo-Hebrew, Qumran Hebrew, Old/Imperial Aramaic, Jewish Palestinian/Babylonian Aramaic, Classical Syriac) are listed by the API as `unsupported` until OCR models, corpora, and evaluation sets exist.

## Stack

Next.js + TypeScript + React + Tailwind CSS v4 frontend · Python 3.11+ FastAPI/Pydantic/Uvicorn backend, Pillow/NumPy (OpenCV optional) · SQLite (stdlib `sqlite3`, versioned migrations) · Tesseract baseline + Kraken adapter for OCR · Moses SMT + Marian NMT adapters for translation (Part 4). CPU-only must remain possible; WSL2/GPU/Docker are optional.

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

Then open http://localhost:3000, upload a supported image (PNG/JPEG/TIFF/WEBP/BMP) and you will see its actual preview and the live capability states. OCR/translation will report *unavailable* until you provision real models — `.\scripts\provision-models.ps1` only checks and reports; it downloads nothing silently.

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

`frontend/` Next.js app · `backend/` FastAPI app (`app/api`, `app/core`, `app/schemas`, `app/services/{preprocessing,ocr,language,morphology,retrieval,translation,verification}`, `app/storage`) · `training/` dataset/SMT/NMT/OCR/evaluation work (nothing trained yet) · `scripts/` PowerShell setup/start/verify/provision-check · `artifacts/manifests/` checksummed dataset & model manifests (binaries live outside source control) · `docs/` contract, build state, handoff, architecture, API, installation, limitations.

Continuity files — read these first in any new session: `docs/PROJECT_CONTRACT.md`, `docs/BUILD_STATE.md`, `docs/PHASE_HANDOFF.md`.

## License

MIT — see `LICENSE`. Corpus/model licences are tracked separately in `artifacts/manifests/`; no corpus data is bundled in Part 1.
