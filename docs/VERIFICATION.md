# Verification — how to test every case yourself

**Status of this document:** the OCR/corpus/morphology code was written to be run by the developer; per the project owner's instruction it has **not** been executed as a test suite by the build assistant, and **no OCR accuracy score exists**. Every case below lists the exact command (Windows PowerShell and bash), and the expected behaviour. The foundation code (monorepo, upload, API shell) was test-run during its own build — those recorded results are kept at the end of this file as historical data.

## Environment setup
```powershell
# PowerShell (repo root)
.\scripts\setup-windows.ps1
.\scripts\provision-ocr.ps1        # Tesseract binary + heb traineddata
.\scripts\import-corpus.ps1       # morphhb/WLC + WEB corpus into SQLite
.\scripts\start-backend.ps1        # terminal 1
.\scripts\start-frontend.ps1       # terminal 2
```
```bash
# bash (repo root)
./scripts/provision-ocr.sh
./scripts/import-corpus.sh
cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Backend test suite (all cases)
```powershell
cd backend; .\.venv\Scripts\Activate.ps1; python -m pytest -q
```
```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: the foundation suite (health, capabilities honesty, upload validation, honest unavailable states, history) plus `tests/test_corpus_ocr.py`:

| Case | Expected behaviour |
|---|---|
| Normalization keys | Exact key keeps diacritics; diacritic-insensitive key removes them and differs. |
| CER/WER metrics | Known-value checks (identical = 0, one substitution in 3 chars = 1/3). |
| Preprocessing, conservative | Derived PNG decodable; step report shows deskew and median NOT applied. |
| Preprocessing, enhanced | Report shows adaptive contrast applied and a deskew angle field (may be 0.0). |
| Exact Hebrew match | Translating the fixture Genesis 1:1 source returns HTTP 200, `translation_method="verified_reference"`, the WEB English from the fixture, `source_references[0].reference="Genesis 1:1"`, `match_type="exact"`, editions + licence present. |
| Diacritic-stripped match | Retrieval of the diacritic-stripped Genesis 1:1 returns `match_type="normalized"` for the same passage. |
| Exact Aramaic match | Daniel 2:4 under `biblical_aramaic` returns its WEB English with citation. |
| One-word variant | Retrieval returns `match=null` (a variant candidate may appear, never as a match); translate returns 503 `translation_model_unavailable`. |
| Cross-language lookup | Daniel 2:4 searched in the Hebrew index (and Genesis 1:1 in the Aramaic index) returns `match=null`. |
| Unseen text | Retrieval `match=null`; translate 503. |
| Corpus capabilities | With the fixture corpus imported: `corpus.status="available"`, per-language counts ≥ 3 each, `morphology.status="available"`. |
| Morphology, known Hebrew word | אֱלֹהִים (Genesis 1:1) returns `found` with a Strong's 430 entry and `word_language="hebrew"` on every entry. |
| Morphology, unknown word | Returns `status="not_found"` with empty entries — no fabricated tags. |
| Morphology, Aramaic separation | מַלְכָּא returns `found` via the Aramaic adapter (all entries `word_language="aramaic"`) and `not_found` via the Hebrew adapter. |
| Morphology without corpus | HTTP 503 `corpus_unavailable` with import instructions. |
| OCR, Hebrew fixture (skips if no binary) | Non-empty Hebrew-script text, `ocr_lang="heb"`, real `mean_confidence`, CER below the lenient a-priori bound recorded in the test (0.65; tighten it from your own measurement). |
| OCR, Aramaic fixture (skips if no binary) | `ocr_profile="biblical_aramaic"` while `ocr_lang="heb"` (Hebrew traineddata; the note states Syriac data is not used). |
| OCR, blank image (skips if no binary) | HTTP 422 `empty_transcription`. |

## Frontend checks
```powershell
cd frontend; npm run typecheck; npm run test; npm run build
```
```bash
cd frontend && npm run typecheck && npm run test && npm run build
```
Expected: typecheck clean; vitest passes, including the export test asserting that a verified-reference result exports its citation and `match_type` in both TXT and JSON; production build succeeds. In the running UI: upload a fixture PNG, choose a preprocessing profile, run OCR (raw text with low-confidence words highlighted and the OCR profile note shown), correct the text, translate — a corpus match shows the citation/provenance panel; non-matching text shows the honest unavailable message.

## OCR measurement (produces the first real scores)
```powershell
cd backend
$env:TESSDATA_PREFIX = "<path to tessdata>"
python ..\training\ocr\generate_fixtures.py --font "C:\Windows\Fonts\david.ttf"
python ..\training\evaluation\evaluate_ocr.py
```
```bash
cd backend
TESSDATA_PREFIX=<path-to-tessdata> .venv/bin/python ../training/ocr/generate_fixtures.py
TESSDATA_PREFIX=<path-to-tessdata> .venv/bin/python ../training/evaluation/evaluate_ocr.py
```
Expected: `training/ocr/fixtures/ocr_measurement.json` is written with the measured CER/WER per fixture, the raw OCR output next to the ground truth, and mean confidence. Whatever numbers come out — good or bad — are the real ones; record them in `docs/BUILD_STATE.md`.

## Corpus importer (data preparation — already run once for the manifest)
```
python -m app.corpus.import_morphhb --download --import-db
```
Recorded parse report from data preparation: 1,890 verses parsed (Genesis + Daniel), 1,885 with aligned WEB English, 1,690 Hebrew / 200 Aramaic passages, 0 duplicates skipped, 0 validation errors; five verses (Genesis 32:33; Daniel 3:31–33; 6:29) have no aligned English due to WLC/WEB verse-numbering differences. Source-file sha256 values are in `artifacts/manifests/datasets.json`. The database import step itself is part of the developer run above (`scripts/import-corpus.*`).

## Historical record — foundation build (actually run at that time)
Recorded when the foundation was built, before the code-only instruction: backend pytest 15 passed; frontend typecheck clean; vitest 2 passed; Next.js build succeeded; live smoke: `/api/health` ok, real PNG upload 200, `/api/translate` honest 503. Tesseract was absent on that machine, so OCR was unavailable — that absence is what the OCR provisioning above addresses.
