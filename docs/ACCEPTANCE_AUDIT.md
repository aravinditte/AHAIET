# Acceptance audit

Each acceptance criterion from the project contract and build brief,
categorised **from code and repository state only**, using these
states:

- **coded** — the implementation exists in the tree; any tests for it
  exist as code only (per the project testing rule, the build
  assistant does not run suites; execution is the developer's step and
  its results, once run, belong in docs/VERIFICATION.md).
- **unit_tested** — dedicated unit tests exist as code for the
  criterion (still not executed by the build assistant).
- **integrated** — exercised end-to-end by an earlier verified build
  step recorded in docs/BUILD_STATE.md.
- **end_to_end_tested** — the full real pipeline (image -> OCR ->
  correction -> translation) has been run and recorded. **Nothing in
  this repository currently holds this state.**
- **blocked** — the code path exists but a named external prerequisite
  is missing; the exact prerequisite is stated.
- **unsupported** — deliberately not provided; reported honestly
  instead of simulated.

A docs link-check (`backend/tests/check_docs_links.py`) verifies that
every path cited below resolves.

## Criteria

| # | Criterion | State | Evidence / prerequisite |
|---|---|---|---|
| 1 | Upload a real image | unit_tested | `POST /api/uploads` with content inspection (`backend/app/services/preprocessing/service.py`); round-trip test as code in `backend/tests/test_integration.py`; atomic-write + conflict tests in `backend/tests/test_remediation.py` |
| 2 | Local OCR | **blocked** | Engine code complete (`backend/app/services/ocr/service.py`, Tesseract TSV + Kraken adapters) and Hebrew traineddata provisioned under `.tools/tessdata`, but the **Tesseract binary is not installed on this machine** — prerequisite: install Tesseract (docs/OCR.md; Windows: `scripts/provision-ocr.ps1 -Install`) |
| 3 | Captured text display | coded | Raw OCR region (read-only, low-confidence words highlighted by occurrence id) in `frontend/src/components/SourceEditor.tsx`; `/api/ocr` and `/api/process` return the transcription |
| 4 | RTL rendering | coded | `dir="rtl" lang="he"` on source regions and per-segment source text (`frontend/src/components/SourceEditor.tsx`, `frontend/src/components/TranslationPanel.tsx`); Hebrew font stack is system/local (`frontend/src/app/globals.css`) |
| 5 | Aramaic not treated as Hebrew | unit_tested | Script alone never classifies (`backend/app/services/language/service.py`); retrieval and morphology are profile-separated (`backend/app/services/retrieval/service.py`, `backend/app/services/morphology/service.py`); ambiguity/profile-choice tests in `backend/tests/test_remediation.py` |
| 6 | Correction editing | unit_tested | Corrected-text editor prefilled from OCR; `/api/translate` keeps `original_ocr_text` (raw, or null without OCR context) and `corrected_source_text` separate (`backend/app/api/routes.py`); lineage tests in `backend/tests/test_remediation.py` |
| 7 | Local translation backend | coded | Verified retrieval + Moses/Marian subprocess adapters, all local (`backend/app/services/translation/service.py`); ordered same-profile fallback in `backend/app/services/translation/selection.py` |
| 8 | Complete English display | unit_tested | Full-passage translation with per-line segments, explicit partial states, and blank-line layout preservation (`frontend/src/components/TranslationPanel.tsx`, `backend/app/services/language/passage.py`); `test_preserve_blank_lines` in `backend/tests/test_remediation.py` |
| 9 | Verified provenance | coded | Provenance block (engine, version, artifact SHA-256, evaluation state) and cited source references with editions and licence (`frontend/src/components/TranslationPanel.tsx`; response built in `backend/app/api/routes.py`) |
| 10 | Trained/evaluated model for unfamiliar passages | **blocked** | Training, evaluation, and inference code complete (docs/TRAINING.md), but **no trained artifact exists**: every SMT/NMT manifest entry is `not_provisioned`. Prerequisite: run a real Moses training run per docs/TRAINING.md. The Aramaic training partition now exists (Ezra, see docs/TRAINING.md) — the earlier zero-training-pairs blocker is resolved as data preparation |
| 11 | Honest unsupported reporting | unit_tested | Script support is computed from evidence in tiers — `model_installed` / `experimentally_evaluated` / `production_supported` — never asserted (`backend/app/services/ocr/script_profiles.py`); tier-gate tests in `backend/tests/test_remediation.py`; unsupported profiles/engines return explicit errors |
| 12 | No API keys | coded | No key exists in configuration, code, or docs; the offline self-check (`backend/app/offline_check.py`) scans for outbound constructs |
| 13 | Offline OCR/translation | **blocked** (OCR leg) | Design and proofs are in place (docs/OFFLINE_OPERATION.md; socket-blocked tests as code in `backend/tests/test_offline.py`); translation/retrieval/morphology run fully offline. The OCR leg cannot be demonstrated until the Tesseract binary prerequisite (criterion 2) is met. The opt-in end-to-end acceptance test exists as code: `backend/tests/test_real_pipeline_acceptance.py` |
| 14 | Copy/export | coded | Copy source/English + TXT/JSON exports with per-action disabled states and surfaced errors (`frontend/src/components/ExportButtons.tsx`, `frontend/src/lib/export.ts`); browser flow specified in `frontend/e2e/translator.spec.ts` |
| 15 | Frontend builds | integrated | `npm run build` / `typecheck` / `test` scripts in `frontend/package.json`; the production build passed during the foundation verification recorded in docs/BUILD_STATE.md, and `.github/workflows/ci.yml` re-checks build+typecheck+vitest on every push (the workflow file itself still needs manual addition by the repository owner — see docs/PHASE_HANDOFF.md) |
| 16 | Backend tests | unit_tested (as code) | Suites under `backend/tests/` covering API, corpus/OCR parsing, translation models, verification, security, offline operation, text processing, integration, and the remediation regressions in `backend/tests/test_remediation.py`; execution is the developer's step (docs/VERIFICATION.md) |
| 17 | Metrics from real test sets | **blocked** | The evaluation harness (`training/evaluation/evaluate_translation.py`) reports only measured runs, refuses selection on `insufficient_test_data`, and records comparability evidence per run — but **no evaluation run has been executed**: there are no recorded BLEU/chrF figures. Prerequisites: full corpus imported, a trained artifact (criterion 10), then run the harness (docs/MODEL_EVALUATION.md). Note: under the book-group split the Hebrew partition has no test verses, so a Hebrew evaluation reports `insufficient_test_data` until a held-out Hebrew source is added |
| 18 | Windows instructions validated | **blocked** | PowerShell instructions are written throughout (README.md, docs/RELEASE.md, `scripts/provision-ocr.ps1`, `scripts/setup-windows.ps1`, `scripts/install-retention-task.ps1`) but **have not been executed on Windows**. Prerequisite: a Windows machine (or VM) run-through of the sequence in docs/RELEASE.md (`test_windows_setup_smoke`) |
| 19 | No fake outputs | unit_tested | Enforced in code: dictionary gloss is never returned as a translation; a near-variant is never a match; an ambiguous match is never verified; verification never labels a translation "correct"; empty/unavailable states are explicit (`backend/app/services/verification/service.py`, `backend/app/services/retrieval/service.py`); decoder empty/alignment output tests in `backend/tests/test_remediation.py` |

## Counts

- **coded: 5** (criteria 3, 4, 7, 9, 12)
- **unit_tested: 7** (criteria 1, 5, 6, 8, 11, 16, 19)
- **integrated: 1** (criterion 15 — foundation build only)
- **end_to_end_tested: 0**
- **blocked: 5** (criteria 2, 10, 13, 17, 18) — prerequisites: Tesseract
  binary installation (2, 13); a real training run (10); an
  evaluation run on a trained artifact (17); a Windows run-through (18)
- **unsupported: 0**
