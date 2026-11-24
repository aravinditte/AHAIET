# Acceptance audit

Each acceptance criterion from the project contract and build brief,
categorised **from code and repository state only**:

- **Implemented** — the code is present, with file evidence.
- **Blocked** — the code path exists but a named external prerequisite
  is missing; the exact prerequisite is stated.
- **Not yet implemented** — no code path exists.

Per the project's testing rule, this audit claims no test results:
tests exist as code for the developer to run (docs/VERIFICATION.md),
and nothing here upgrades a category based on an unrun test.

## Criteria

| # | Criterion | Category | Evidence / prerequisite |
|---|---|---|---|
| 1 | Upload a real image | Implemented | `POST /api/uploads` with content inspection (`backend/app/services/preprocessing/service.py: validate_and_decode`); UI `frontend/src/components/UploadPanel.tsx`; round-trip test as code in `backend/tests/test_integration.py` |
| 2 | Local OCR | **Blocked** | Engine code complete (`backend/app/services/ocr/`, Tesseract TSV + Kraken adapters) and Hebrew traineddata provisioned under `.tools/tessdata`, but the **Tesseract binary is not installed on this machine** — prerequisite: install Tesseract (docs/OCR.md) or run `scripts/provision-ocr` where it can install the binary |
| 3 | Captured text display | Implemented | Raw OCR region (read-only, low-confidence words highlighted) in `frontend/src/components/SourceEditor.tsx`; `/api/ocr` and `/api/process` return the transcription |
| 4 | RTL rendering | Implemented | `dir="rtl" lang="he"` on source regions and per-segment source text (`SourceEditor.tsx`, `TranslationPanel.tsx`); Hebrew font stack is system/local (`globals.css`) |
| 5 | Aramaic not treated as Hebrew | Implemented | Script alone never classifies (`backend/app/services/language/service.py: suggest_language`); retrieval and morphology are profile-separated (`services/retrieval`, `services/morphology`); separation tests as code in `backend/tests/test_text_processing.py` |
| 6 | Correction editing | Implemented | Corrected-text editor prefilled from OCR; `/api/translate` prefers `corrected_source_text` and preserves both texts in the response (`backend/app/api/routes.py`); correction-flow test as code in `test_integration.py` |
| 7 | Local translation backend | Implemented | Verified retrieval + Moses/Marian subprocess adapters, all local (`backend/app/services/translation/`); selection logic in `selection.py` |
| 8 | Complete English display | Implemented | Full-passage translation with per-line segments and explicit partial states (`TranslationPanel.tsx`, `backend/app/services/language/passage.py`) |
| 9 | Verified provenance | Implemented | Provenance block (engine, version, artifact SHA-256, evaluation state) and cited source references with editions and licence (`TranslationPanel.tsx`; response built in `routes.py` / translation services) |
| 10 | Trained/evaluated model for unfamiliar passages | **Blocked** | Training, evaluation, and inference code complete (docs/TRAINING.md), but **no trained artifact exists**: every SMT/NMT manifest entry is `not_provisioned`. Prerequisite: run a real Moses training run per docs/TRAINING.md. For Aramaic there is an additional data prerequisite (criterion noted in docs/TROUBLESHOOTING.md: zero Aramaic training pairs under the recorded split) |
| 11 | Honest unsupported reporting | Implemented | Script support is computed from evidence (checkpoint + measured CER record), never asserted (`backend/app/services/scripts.py`); unsupported profiles/engines return explicit errors; readiness panel shows real states |
| 12 | No API keys | Implemented | No key exists in configuration, code, or docs; the offline self-check (`backend/app/offline_check.py`) scans for outbound constructs |
| 13 | Offline OCR/translation | **Blocked** (OCR leg) | Design and proofs are in place (docs/OFFLINE_OPERATION.md; socket-blocked tests as code in `backend/tests/test_offline.py`); translation/retrieval/morphology run fully offline today. The OCR leg cannot be demonstrated on this machine until the Tesseract binary prerequisite (criterion 2) is met |
| 14 | Copy/export | Implemented | Copy source/English + TXT/JSON exports (`frontend/src/components/ExportButtons.tsx`, `frontend/src/lib/export.ts`); browser flow specified in `frontend/e2e/translator.spec.ts` |
| 15 | Frontend builds | Implemented | `npm run build` / `typecheck` / `test` scripts in `frontend/package.json`; the production build passed during the foundation verification recorded in docs/BUILD_STATE.md, and `.github/workflows/ci.yml` re-checks build+typecheck+vitest on every push (workflow not yet executed — see the manual-addition note in docs/PHASE_HANDOFF.md) |
| 16 | Backend tests | Implemented (as code) | Suites under `backend/tests/` covering API, corpus/OCR parsing, translation models, verification, security, offline operation, text processing, and integration; execution is the developer's step per the project testing rule (docs/VERIFICATION.md) |
| 17 | Metrics from real test sets | **Blocked** | The evaluation harness exists (`training/evaluation/evaluate_translation.py`) and reports only measured runs, but **no evaluation run has been executed**: there are no recorded BLEU/chrF++ figures. Prerequisites: full corpus imported, a trained artifact (criterion 10), then run the harness (docs/TRAINING.md) |
| 18 | Windows instructions validated | **Blocked** | PowerShell instructions are written throughout (README, docs/RELEASE.md, scripts/*.ps1) but **have not yet been executed on Windows**. Prerequisite: a Windows machine (or VM) run-through of the sequence in docs/RELEASE.md |
| 19 | No fake outputs | Implemented | Enforced in code: dictionary gloss is never returned as a translation; a near-variant is never a match; verification never labels a translation "correct"; empty/unavailable states are explicit (translation services, `services/verification.py`, retrieval service) |

## Counts

- **Implemented: 14** (criteria 1, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 19)
- **Blocked: 5** (criteria 2, 10, 13, 17, 18) — prerequisites: Tesseract
  binary installation (2, 13); a real training run, plus an Aramaic
  data decision (10); an evaluation run on a trained artifact (17);
  a Windows run-through (18)
- **Not yet implemented: 0**
