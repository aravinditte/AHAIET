# BUILD STATE — AHAIET
Current phase: **Part 1 of 5 — Foundation. COMPLETE (with OCR/translation honestly unavailable).**
Build machine: Linux VM, Python 3.12.3, Node v24.22.1, npm 10.9.4, git 2.43.0, CPU only. `which tesseract` -> not found (exit 1).

## Feature status (evidence-based)
| Feature | Status | Evidence |
|---|---|---|
| Monorepo scaffold (frontend/backend/training/scripts/artifacts/docs) | done | file tree in repo |
| Backend API (all routes in docs/API.md) | done | pytest 15 passed; live uvicorn smoke (below) |
| Config (env-typed Settings: upload bytes/pixels, storage, retention, db path) | done | backend/app/core/config.py; pixel-limit test uses env/dataclass override |
| SQLite schema + migrations (schema_version, language_profiles, model_metadata, reference_passages EMPTY, history, jobs) | done | backend/app/storage/db.py MIGRATIONS v1; health db_ok=true live |
| Upload validation by content + hash storage + preview fetch | done | tests: valid PNG 200 + byte-identical preview; text-named-.png 400 invalid_image; oversized pixels 400 |
| Frontend upload/preview, RTL source editor (raw vs corrected separate), readiness panel, translate, copy/export, dark/light, reset | done | npm run build passes; export vitest 2 passed incl. Hebrew Unicode round-trip |
| OCR (Tesseract adapter: shutil.which + subprocess; Kraken import adapter) | implemented, **unavailable on this machine** | no tesseract binary; /api/capabilities ocr.status=unavailable; /api/ocr 503; process job ends failed with reason (all tested) |
| Translation (manifest-driven Moses/Marian adapters) | implemented, **unavailable** | every models.json entry not_provisioned/path null; /api/translate 503 translation_model_unavailable; empty text 400 (tested) |
| Language suggestion | done, conservative | returns "uncertain" + warning without user selection; never Hebrew-from-script |
| Morphology / retrieval / verification | interface only, not_provisioned | services/*/service.py status() |
| Datasets / corpora | none | datasets.json datasets=[]; reference_passages empty |
| Training | none | training/*/README.md placeholders only |

## Dependencies installed (this machine)
Backend venv backend/.venv: fastapi 0.165.0, uvicorn 0.54.0, pydantic 2.14.4, Pillow 13.0.0, numpy 2.5.5, python-multipart 0.0.34, pytest 9.2.0, httpx 0.28.1. OpenCV: NOT installed (optional extra) — capabilities report opencv=false.
Frontend: next 15.x, react 19, tailwindcss v4, vitest 2 (npm install completed).
Locally available OCR/translation models: **none**.

## Exact commands & results (Part 1)
- `which tesseract` -> not found (exit 1)
- `backend/.venv/bin/pip install -e "backend/.[dev]"` -> Successfully installed (fastapi/pydantic/pytest/httpx/…)
- `backend/.venv/bin/python -m pytest -q` -> **15 passed**, 1 warning (Starlette TestClient deprecation notice) in 0.42s. One initial collection error (tests/__init__.py broke conftest import) was fixed by removing it.
- `npm install` -> completed
- `npm run typecheck` (tsc --noEmit) -> exit 0, no errors
- `npx vitest run` -> **Test Files 1 passed; Tests 2 passed**
- `npm run build` -> success; route `/` 4.35 kB, First Load JS 107 kB, static prerender
- Live smoke: uvicorn on 127.0.0.1:8765 -> /api/health {status:ok, db_ok:true}; /api/capabilities ocr unavailable + translation unavailable + opencv false; POST /api/uploads (real 8x8 PNG) -> 200 with sha256 id; POST /api/translate -> 503 translation_model_unavailable. Server stopped after the check.

## Next steps
Part 2: provision Tesseract + heb traineddata, wire preprocessing/OCR evaluation, Kraken path. See docs/PHASE_HANDOFF.md.
