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
| 10 | Trained/evaluated model for unfamiliar passages | **blocked** | Training, evaluation, and inference code complete (docs/TRAINING.md), but **no trained artifact exists**: every SMT/NMT manifest entry is `not_provisioned`. Prerequisite: run a real Moses training run per docs/TRAINING.md. Training partitions now exist for both profiles (Hebrew 906 pairs; Aramaic 67 pairs from Ezra — enough for the SMT minimum of 50, far below the Marian 500-pair gate, which remains unmet) |
| 11 | Honest unsupported reporting | unit_tested | Script support is computed from evidence in tiers — `engine_installed` / `operational` / `evaluated_on_dataset` / `validated_for_production` (renamed and tightened by NEW-17; the old labels are superseded) — never asserted (`backend/app/services/ocr/script_profiles.py`); tier-gate tests in `backend/tests/test_rereview.py`; unsupported profiles/engines return explicit errors |
| 12 | No API keys | coded | No key exists in configuration, code, or docs; the offline self-check (`backend/app/offline_check.py`) scans for outbound constructs |
| 13 | Offline OCR/translation | **blocked** (OCR leg) | Design and proofs are in place (docs/OFFLINE_OPERATION.md; socket-blocked tests as code in `backend/tests/test_offline.py`); translation/retrieval/morphology run fully offline. The OCR leg cannot be demonstrated until the Tesseract binary prerequisite (criterion 2) is met. The opt-in end-to-end acceptance test exists as code: `backend/tests/test_real_pipeline_acceptance.py` |
| 14 | Copy/export | coded | Copy source/English + TXT/JSON exports with per-action disabled states and surfaced errors (`frontend/src/components/ExportButtons.tsx`, `frontend/src/lib/export.ts`); browser flow specified in `frontend/e2e/translator.spec.ts` |
| 15 | Frontend builds | integrated | `npm run build` / `typecheck` / `test` scripts in `frontend/package.json`; the production build passed during the foundation verification recorded in docs/BUILD_STATE.md, and `.github/workflows/ci.yml` re-checks build+typecheck+vitest on every push (the workflow file itself still needs manual addition by the repository owner — see docs/PHASE_HANDOFF.md) |
| 16 | Backend tests | unit_tested (as code) | Suites under `backend/tests/` covering API, corpus/OCR parsing, translation models, verification, security, offline operation, text processing, integration, and the remediation regressions in `backend/tests/test_remediation.py`; execution is the developer's step (docs/VERIFICATION.md) |
| 17 | Metrics from real test sets | **blocked** | The evaluation harness (`training/evaluation/evaluate_translation.py`) reports only measured runs, refuses selection on `insufficient_test_data`, and records comparability evidence per run — but **no evaluation run has been executed**: there are no recorded BLEU/chrF figures. Prerequisites: full corpus imported, a trained artifact (criterion 10), then run the harness (docs/MODEL_EVALUATION.md). Note: since the NEW-02 split redesign both profiles have test partitions (Hebrew: Ruth, 85 pairs; Aramaic: Daniel chs. 3–7, 150 pairs), so an evaluation run is no longer blocked by missing test data for either profile |
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

## Re-review remediation (findings NEW-01..NEW-27)

State per finding, from code and repository state only. "Addressed
in code" means the implementation and its regression tests exist in
the tree; per the project testing rule they have not been executed
by the build assistant.

| Finding | State | Evidence |
|---|---|---|
| NEW-01 group integrity key | addressed in code | `training/datasets/prepare_parallel.py` keys groups by (language_profile, book, chapter); regression tests in `training/tests/test_remediation_training.py` |
| NEW-02 split redesign | addressed in code (data preparation run) | Ruth imported as the held-out Hebrew test book; Daniel Aramaic ch. 2 validation / chs. 3–7 test; parse + leakage checks recorded in `artifacts/manifests/datasets.json` (Hebrew 906/996/85, Aramaic 67/46/150 pairs) |
| NEW-03 end-to-end proof | **blocked** | No real-pipeline run exists. Prerequisites and the exact acceptance sequence are listed below this table. Nothing in this repository is labelled end-to-end tested |
| NEW-04 selection basis | addressed in code | Single qualifying engine selectable, labelled `selection_basis="single_evaluated_engine"`, `comparable=false`; `head_to_head` only for >= 2 engines on one run signature (`training/evaluation/evaluate_translation.py`, `backend/app/services/translation/selection.py`) |
| NEW-05 executable doubles + command vectors | addressed in code | `backend/tests/double_factory.py`; adapters accept string / shlex / list command forms via `backend/app/services/translation/command.py` |
| NEW-06 frontend race guards | addressed in code | Input fingerprint + sequence + abort in `frontend/src/app/page.tsx`; deterministic spec `frontend/e2e/race.spec.ts` |
| NEW-07 OCR supersession | addressed in code | Starting OCR clears active OCR state (labelled history only) and disables translation until completion; engine/script/profile changes invalidate OCR state |
| NEW-08 cross-profile evidence | addressed in code | Verified-in-one + ambiguous-in-another -> `profile_choice_required` (`backend/app/services/translation/service.py`) |
| NEW-09 line-structure routing | addressed in code | Any line boundaries -> passage flow; exact blank-line assertions in tests |
| NEW-10 categorized engine failures | addressed in code | All-timeout -> 504 `translation_timeout` with attempt records; all-unavailable -> 503; mixed -> most severe |
| NEW-11 token in UI | addressed in code | Token field stored only in sessionStorage; header attached by the API client; preview via authenticated Blob fetch -> object URL |
| NEW-12 token guard matrix | addressed in code | `_require_access` on uploads read, process, job read/result/cancel, history read/delete; 401 matrix test in `backend/tests/test_rereview.py` |
| NEW-13 decoder cwd + absolute export paths | addressed in code | Adapters launch with cwd=artifact_dir; SMT/Marian exports write absolute paths; export verification resolves from an unrelated cwd |
| NEW-14 metric invalidation + run records | addressed in code | Runs archive prior metrics on every engine card for the profile as stale; scores count only with a valid run record |
| NEW-15 job ownership/heartbeat | addressed in code | Migration v5 (owner_id, heartbeat_at); lifespan startup recovery fails only stale-heartbeat jobs and surfaces failures |
| NEW-16 OCR job deadline | addressed in code | Job OCR runs in the `app.services.ocr.worker_entry` subprocess bounded by the job deadline; expiry terminates it with `ocr_timeout` |
| NEW-17 script tiers | addressed in code | engine_installed / operational / evaluated_on_dataset / validated_for_production with the tightened gates (script identity equality, recomputed dataset hash, >= 50 samples, CER <= 0.20, WER recorded, checkpoint hash) |
| NEW-18 languages status | addressed in code | `GET /api/languages` derives translation_status live (retrieval_available / model_evaluated / model_installed_unevaluated / not_provisioned) sharing the capabilities computation |
| NEW-19 export fallback | addressed in code | Source payload = corrected if nonempty else raw OCR; buttons enabled when either exists |
| NEW-20 tesseract probe honesty | addressed in code | Failed --list-langs probe -> probe_failed=true, usable=false; file presence reported separately |
| NEW-21 token offsets | addressed in code | Tokens/spans carry code-point offsets from both engines; the UI highlights by slicing offsets and labels the fallback approximate |
| NEW-22 preprocessing global state | addressed in code | MAX_IMAGE_PIXELS set once at startup; explicit per-request ceiling; derived-memory budget; downscaled classifier pass decides the full-resolution median |
| NEW-23 grapheme clusters | addressed in code | Combining-aware clusterer in the Kraken adapter; count mismatch -> confidence_unavailable |
| NEW-24 acceptance test strength | addressed in code | Uncorrected OCR scored with CER/WER gates for both Hebrew and Aramaic cases; corpus provisioned as an explicit fixture step; AHAIET_RELEASE_GATE=1 converts skips to failures. The test itself runs only on a provisioned machine (see NEW-03) |
| NEW-25 exact assertions | addressed in code | Exact blank-line assertions; lineage positive path via a real fixture-corpus match asserting 200 + lineage fields; Playwright race specs use route interception |
| NEW-26 docs currency | addressed in code | docs/LIMITATIONS.md and docs/BUILD_STATE.md rewritten from the manifests; historic counts moved to a dated superseded changelog; `backend/tests/test_docs_consistency.py` guards books/counts/statuses/security controls |
| NEW-27 artifact integrity | addressed in code | `verify_artifacts(settings, force=True)` rehashes content regardless of mtime/size; cache fast path bounded by the integrity TTL; startup re-verification; SHA-named immutable layout documented in docs/TRAINING.md |

### NEW-03 acceptance sequence (provisioned machine)

Run in order; the criterion closes only when every step's output is
recorded in docs/VERIFICATION.md.

1. Provision Tesseract + heb traineddata (Windows:
   `scripts/provision-ocr.ps1 -Install`; Linux: package manager per
   docs/OCR.md) and confirm `GET /api/capabilities` reports the OCR
   engine usable (probe_failed=false).
2. Generate the fixture images: `python training/ocr/generate_fixtures.py`.
3. Import the corpus into the app database:
   `python -m app.corpus.import_morphhb --download --import-db`
   (from backend/).
4. Run the acceptance gate in release mode:
   `AHAIET_RELEASE_GATE=1 python -m pytest tests/test_real_pipeline_acceptance.py -q -m model_required`
   (PowerShell: `$env:AHAIET_RELEASE_GATE='1'; python -m pytest tests/test_real_pipeline_acceptance.py -q -m model_required`).
   Both cases (Genesis 1:1 Hebrew, Daniel 2:4 Aramaic) must PASS —
   in release-gate mode a skip is a failure.
5. Record the run (date, machine, Tesseract version, CER/WER values
   from the gate) in docs/VERIFICATION.md, then update criterion 2,
   13 and this section.
