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

## SMT/NMT training and translation evaluation (coded; not yet run)

Per the owner's instruction this code was written to be run by the developer; **nothing in this section has been executed** — no training run, no evaluation, no scores exist. Commands are given for Windows PowerShell and WSL2/bash. Prerequisites: corpus imported (above), plus the Moses/GIZA++/KenLM toolchain inside WSL2 and/or a Marian build (docs/TRAINING.md), and `pip install -r training\requirements.txt` for sacrebleu/SentencePiece.

### Dataset preparation
```powershell
python training\datasets\prepare_parallel.py
python -m pytest training\tests -q
```
```bash
python3 training/datasets/prepare_parallel.py
python3 -m pytest training/tests -q
```
| Case | Expected behaviour |
|---|---|
| Hebrew prepared files | `training/datasets/prepared/biblical_hebrew/` holds train (693 pairs) / validation (839) / test (157) source+vocalized, source+consonantal, and target files, one verse per line and line-aligned; `dataset_card.json` counts match the files and every file's sha256 in the card matches the file on disk. |
| Aramaic prepared files | Train and validation files exist but are EMPTY (0 pairs); test holds 196 pairs; the card's `small_corpus.statement` and `prep_report.json`'s data statement say plainly that all Aramaic passages sit in the held-out Daniel test partition and no Aramaic training data exists yet. |
| Empty-English verses | 5 verses (Genesis 32:33; Daniel 3:31–33; 6:29) are excluded from the parallel files and listed in the card's `excluded_empty_english_references` — not aligned to neighbouring verses. |
| Leakage checks | `leakage_report.json` shows no cross-split exact/nodiac duplicates; near-duplicates (if any) are flagged with references. The training tests plant a cross-split duplicate and a pointing-only duplicate and expect a hard failure (exit code 2 from the CLI). |
| Group integrity | The training tests confirm no (book, chapter) group spans two splits for the fixture, and that a synthetic group spanning train/test is rejected. |
| Views | The vocalized train source contains niqqud (e.g. shewa); the consonantal file for the same lines contains none. Canonical text is unchanged in the corpus itself. |

### Moses SMT training (WSL2)
```powershell
.\scripts\smt-train.ps1 -Profile biblical_hebrew
.\scripts\smt-train.ps1 -Profile biblical_aramaic
```
```bash
./scripts/smt-train.sh biblical_hebrew
python3 training/smt/train_smt.py --profile biblical_hebrew
```
| Case | Expected behaviour |
|---|---|
| Hebrew, full toolchain present | Steps complete in order in `training/smt/work/hebrew/train.log`; `artifacts/models/smt/hebrew/` gains moses.ini + phrase table + LM + vocabulary.source.txt + model_card.json (tool versions recorded from the tools themselves); the manifest entry `moses-biblical-hebrew-en` flips to `provisioned` with path/checksum/version; GET /api/models then reports `artifact_state="trained_but_not_evaluated"`, `ok=true`. |
| Hebrew, KenLM missing | The run stops BEFORE training with the KenLM install message (exit 3). No artifact directory is completed and the manifest is unchanged — no LM is faked. |
| Hebrew, MOSES_HOME missing | Tokenization/cleaning fall back to the repository implementations WITH the substitutions written into train.log; the run stops at train-model.perl with install instructions (exit 3), keeping the real intermediate files. |
| Aramaic | Stops with exit 4: 0 training pairs under the recorded split strategy, with the explanation. No artifact, no manifest change. |
| Tuning | With the moses binary + mert-moses.pl present, MERT runs on the validation split and the tuned moses.ini is exported; without them the untuned model is exported and the skip + reason are recorded in the model card's `tuning` block. |

### Marian NMT training
```powershell
.\scripts\nmt-train.ps1 -Profile biblical_hebrew
.\scripts\nmt-train.ps1 -Profile biblical_aramaic
```
```bash
./scripts/nmt-train.sh biblical_hebrew
python3 training/nmt/train_nmt.py --profile biblical_aramaic
```
| Case | Expected behaviour |
|---|---|
| Aramaic data gate | Exit 3 (an expected outcome, not a crash). `artifacts/models/nmt/aramaic/not_ready.json` + `not_ready.md` state: 0 training pairs, configured minimum 500, the split-strategy reason, and what would change it. No checkpoint is created; the manifest is unchanged. |
| Hebrew, Marian present | Joint SentencePiece vocabulary is built (the log says whether the Python package or spm_train was used); training runs from the rendered `training/nmt/work/hebrew/config.yml`; export writes model.npz + vocab.spm + decoder-config.yml + vocabulary.source.txt + model_card.json under `artifacts/models/nmt/hebrew/`; the manifest entry flips to `provisioned`. |
| Hebrew, Marian binary missing | Vocabulary + rendered config are produced and kept; the run then stops with the install message (exit 3). No checkpoint, no manifest change. |
| Fine-tuning | `--pretrained <local file>` adds `pretrained-model:` to the rendered config; a nonexistent path stops the run with an error before the data gate's training steps. Nothing is ever downloaded. |
| GPU variant | `--config-variant gpu` renders the `-gpu` config template (device 0); on a CPU-only machine use the default CPU variant. |

### Backend integration (trained models)
```powershell
cd backend; .\.venv\Scripts\Activate.ps1; python -m pytest -q
```
```bash
cd backend && .venv/bin/python -m pytest -q
```
| Case | Expected behaviour |
|---|---|
| Adapter tests (tests/test_translation_models.py) | Artifact resolution accepts a complete Moses/Marian fixture directory and lists the exact missing piece for an incomplete one; selection defaults to Moses with no recorded metrics and prefers the higher recorded chrF++ when both have metrics; selection for Aramaic stays empty when only Hebrew is provisioned. (Decoder binaries are tiny echo test doubles inside the tests — fixtures for the subprocess contract, not models.) |
| Translate via trained model | With a provisioned artifact, POST /api/translate for non-corpus text returns 200 with `engine`, `model_version`, `artifact_sha256`, `coverage`, and OOV words named in both `coverage.oov_words` and `warnings`. GET /api/capabilities shows the profile's engine + evaluation state under `translation.per_profile`; the other profile is unaffected. |
| Incomplete artifact | Deleting one required file (e.g. the LM) makes translate return 503 naming that piece, and /api/models reports `artifact_state="provisioned_missing_files"` with the same list. |
| Verified reference unchanged | A corpus-matching text still returns `translation_method="verified_reference"` with citations and null model fields — retrieval outranks trained models. |

### Translation evaluation harness
```powershell
.\scripts\evaluate-translation.ps1 -Profile biblical_hebrew
.\scripts\evaluate-translation.ps1 -Profile biblical_aramaic
```
```bash
./scripts/evaluate-translation.sh biblical_hebrew
python3 training/evaluation/evaluate_translation.py --profile biblical_aramaic
```
| Case | Expected behaviour |
|---|---|
| Reports written | `artifacts/benchmarks/<profile>-translation-eval.json` + `.md` appear, with the metric implementation named (sacrebleu, or the labelled pure-Python fallback). |
| Dictionary baseline | Present and labelled "dictionary_gloss_baseline — not a sentence translation", with gloss output (lemma/Strong's identifiers, unknown words in ⟦ ⟧) and a low score — that low score is the honest floor, not a bug. |
| Unavailable engines | Any engine without a complete artifact/binary is listed `unavailable` WITH its reason and null scores — never zeros. |
| Retrieval caveat | The retrieval row and the report header state that test verses come from the same corpus as the retrieval index, so its coverage is an upper-bound reference figure. |
| Selection record | After a run where at least one trained engine was evaluated, the winner's model_card.json gains real `metrics` + `selection`, its manifest entry gains `evaluation` + `selection`, and /api/models then reports `artifact_state="evaluated"` with `chrf_pp`. With no trained engine evaluated, no record is written and the backend keeps the documented default order. |
| Failure examples | Each evaluated engine lists its five lowest-scoring verses with source, reference English, and its actual output. |
| Human review | `training/evaluation/human_review_template.md` is filled in by a reviewer for any engine whose scores will be cited; the template ships with blank scores. |

### Frontend checks (trained-model display)
```powershell
cd frontend; npm run typecheck; npm run test; npm run build
```
Expected: typecheck clean; vitest passes including the export case asserting engine/model-version/coverage lines in TXT and JSON exports; in the running UI, a translation produced by a trained model shows the engine, model version, artifact hash prefix, evaluation state, and source-token coverage with OOV words under the translation; a verified-reference result shows its citation panel as before.

## Hybrid verification, complete passages, historical recognition, performance (coded; NOT YET RUN)

Everything in this section is code-complete and syntax-checked only. No test, training run, evaluation, or inference in this section has been executed. Expected behaviour is stated per case; record the actual results in docs/BUILD_STATE.md when you run them.

### Backend cases (verification, passages, routing, cache, Kraken paths)

```powershell
# PowerShell (repo root)
cd backend; .\.venv\Scripts\python.exe -m pytest tests\test_hybrid.py -q
```
```bash
# bash (repo root)
cd backend && .venv/bin/python -m pytest tests/test_hybrid.py -q
```

| Case | Expected behaviour |
|---|---|
| Negation mismatch | Source "לֹא תִּגְנֹב" with candidate "You shall steal": the `negation` check is `warn` with source_negations=1, candidate_negations=0. With "You shall not steal" the check is `pass`. |
| Number mismatch | Source "שְׁנֵי לֻחֹת" with candidate "three tablets": the `numbers` check is `warn`, missing_values=[2], extra_values=[3]. With "two tablets" it is `pass`. |
| Coverage with the committed fixture corpus | Genesis 1:1 source + its real WEB English: `source_coverage` is `pass` with coverage_ratio ≥ 0.6. An unrelated English candidate yields `warn`/`fail` with the uncovered source tokens listed explicitly. |
| Coverage without a corpus | On an empty database, `source_coverage` is `not_applicable` (never a guessed score), and the report's overall_status is never the word "correct" — the status vocabulary is no_issues_found / warnings / high_risk. |
| Reference agreement divergence | Genesis 1:1 source + an unrelated candidate + the verse's WEB English as the verified reference: `reference_agreement` is `warn` (evidence only — never a rejection). |
| Translate response shape | POST /api/translate for Genesis 1:1 returns `verification` (checks incl. source_coverage), `provenance` (engine verified_reference, retrieval_citation.reference "Genesis 1:1"), and `cached=false`. |
| Evaluated beats unevaluated | With a Moses artifact (no recorded metrics) and a Marian artifact (chrF++ recorded in its model card) as test doubles, translation uses Marian, `unevaluated_model=false`, provenance.evaluation_state="evaluated". |
| Unevaluated engine flagged | With only the unevaluated Moses test double, the response has `unevaluated_model=true`, a warning naming it, and provenance carrying engine + dataset card hash. |
| Variant never a translation | A pointing-variant of Genesis 1:1 returns HTTP 503; the body has no english_translation; any variant_candidate is labelled match_type "normalized_variant". |
| Passage partial | Genesis 1:1 + an unseen line: status `partial`; segment 0 translated with the cited English; segment 1 `unavailable` with english_translation null; the reassembled English keeps the line structure with the untranslated line empty. |
| Passage completed / failed | Two known verses (with the blank line between them preserved) -> `completed`. Two unknown lines -> `failed` with english_translation null and no fabricated segment. |
| Passage limits | With AHAIET_MAX_SEGMENTS=1, a two-line passage fails with error code `too_many_segments`; over-length input fails with `passage_too_long`. |
| Translation cache | Two identical trained-model requests (echo test double counting its invocations): the second has `cached=true`, provenance keeps the original engine, and the engine ran exactly once. Set AHAIET_TRANSLATION_CACHE=false to disable. |
| Retrieval never cached | Two identical verified-reference requests: both `cached=false`, and the translation_cache table stays empty — the cache is consulted only after retrieval misses. |
| Process stage timings | POST /api/process response and GET /api/jobs/{id}/result both carry `stage_timings_ms` (an object; on this machine, where OCR is unavailable, the job still fails honestly at the OCR stage and the timings object is present). |

### Script support matrix cases

```powershell
# PowerShell — backend running (scripts\start-backend.ps1)
Invoke-RestMethod http://127.0.0.1:8000/api/scripts | ConvertTo-Json -Depth 6
```
```bash
# bash
curl -s http://127.0.0.1:8000/api/scripts
```

| Case | Expected behaviour |
|---|---|
| Default matrix | hebrew_square follows Tesseract provisioning; paleo_hebrew, imperial_aramaic, jewish_babylonian_aramaic_script, classical_syriac_estrangela are all `unsupported` with a reason naming the missing evaluation record. |
| No silent fallback | POST /api/ocr with engine=kraken + script_profile=paleo_hebrew returns 422 `script_unsupported`; engine=tesseract + script_profile=imperial_aramaic also returns 422 `script_unsupported`. |
| Support only from evidence (test-local) | The test suite fabricates a checkpoint file + evaluation record inside a temp directory: a record whose checkpoint_sha256 does not match the file on disk leaves the profile `unsupported`; a matching record flips it to `supported` with the CER from the record. This fabrication exists only in the test — nothing shipped claims support. |
| Kraken adapter honest paths | With the Kraken package absent, `kraken_adapter.status` reports available=false with a reason, and recognize() raises `kraken_unavailable` (or `kraken_checkpoint_missing` when the package exists but the file does not). With a Kraken whose documented pipeline callables are missing, the adapter raises the incompatible error rather than crashing. |

### Kraken provisioning, training, and HTR evaluation (commands; nothing run)

```powershell
# PowerShell (repo root) — checks WSL2 and prints the in-WSL2 install commands
.\scripts\provision-kraken.ps1
# Train inside WSL2 via the wrapper (data dir must contain provenance.txt + train\ line pairs)
.\scripts\train-kraken.ps1 -Profile paleo_hebrew -DataDir D:\kraken-data\paleo
```
```bash
# bash (repo root, Linux/WSL2)
./scripts/provision-kraken.sh
./scripts/train-kraken.sh paleo_hebrew /path/to/kraken-data/paleo
# fine-tune from an existing local checkpoint:
./scripts/train-kraken.sh paleo_hebrew /path/to/kraken-data/paleo /path/to/base.mlmodel
# evaluate the exported checkpoint on held-out labelled lines:
backend/.venv/bin/python training/evaluation/evaluate_htr.py --profile paleo_hebrew \
  --checkpoint artifacts/models/kraken/paleo_hebrew/model.mlmodel \
  --test-dir /path/to/kraken-data/paleo/test
# training-side unit tests for the score aggregation:
backend/.venv/bin/python -m pytest training/tests/test_evaluate_htr.py -q
```

| Case | Expected behaviour |
|---|---|
| Provisioning | The package + `ketos` become available; GET /api/capabilities shows ocr.kraken.available=true with the detected version. No script status changes — provisioning alone is not support. |
| Training without provenance | train_kraken.py exits 2 naming the missing provenance.txt / line pairs; nothing is exported. |
| Training without ketos | Exits 3 with the provisioning instructions; nothing is exported. |
| Training run | ketos trains; the newest checkpoint is exported to artifacts/models/kraken/<profile>/model.mlmodel with training_card.json (provenance, line count, checkpoint sha256) and the manifest entry flips to provisioned. The profile is STILL `unsupported` in /api/scripts until an evaluation record exists. |
| HTR evaluation | evaluate_htr.py writes artifacts/benchmarks/htr-eval-<profile>.json with measured CER/WER, the checkpoint sha256, line counts, and per-line detail; only then does /api/scripts report the profile `supported`. With no Kraken installed it exits 3; with unpaired test data it exits 2 listing the problems. |
| HTR score unit tests | Identical reference/hypothesis -> CER 0 / WER 0; one substitution in 3 chars -> CER 0.3333; aggregation is micro-averaged over total reference length; orphan line images are reported as data problems. |

### Frontend checks (verification panel, segments, scripts, export)

```powershell
cd frontend; npm run typecheck; npm run test; npm run build
```
Expected: typecheck clean; vitest passes including the export case asserting the verification summary + provenance in TXT and JSON exports; in the running UI: the translation panel shows provenance (engine, evaluation state, citation, cache/unevaluated flags), the verification checks list with the plain-language note that checks flag risks and do not prove correctness, a per-line segment breakdown with a partial banner when a passage is partial, collapsible stage timings, the script support matrix with unsupported reasons, and OCR engine/script selectors whose unsupported choices produce the explicit backend error rather than a silent substitution.

## Security, offline, browser E2E, and CI cases (not yet run)

Added with the security and release hardening work. Everything in this
section is **not yet run**; run it and record actual results in
docs/BUILD_STATE.md.

### Dependency hygiene (no network)

```powershell
scripts\check-dependencies.ps1            # bash: ./scripts/check-dependencies.sh
```
Expected: a table of declared bounds vs installed versions from the
backend environment; every row OK, or a clear MISMATCH line naming the
package; exit code 0 unless `--strict` is passed with a mismatch.

### Backend security/offline/text/integration suites

```powershell
cd backend
python -m pytest tests\test_security.py tests\test_offline.py tests\test_text_processing.py tests\test_integration.py -q
```

| Case | Expected behaviour |
|---|---|
| Security headers | /api/health and a 404 both carry nosniff, DENY, no-referrer, CSP default-src 'self' |
| CORS | Origin http://localhost:3000 is allowed; http://evil.example gets no allow-origin header and no preflight grant |
| Rate limit | With a limit of 3/min, the 4th POST /api/translate returns 429, code rate_limited, Retry-After ≥ 1; health is unaffected |
| Body ceiling | With AHAIET_REQUEST_MAX_BYTES equivalent of 64, an oversized JSON POST returns 413 request_too_large |
| Retention dry-run | On seeded tmp data (one 90-day-old upload + history row, one fresh of each), dry-run reports 1 upload + 1 history deletion and deletes nothing |
| Retention sweep | The real sweep deletes only the aged file/row; the fresh ones remain |
| History disabled | With history disabled: GET /api/history returns enabled:false + status disabled; a process run writes zero history rows |
| Offline static scan | `python -m app.offline_check` exits 0; the only findings are the allowlisted setup-only importer |
| Offline runtime | With socket.connect blocked, health/capabilities pass and the fixture Genesis 1:1 verified translation returns 200 with the corpus English |
| Text processing | NFC composes; niqqud preserved in exact keys and stripped only in nodiac keys; maqqef splits; final letters fold only in search keys; passage split/reassemble preserves order and blank-line gaps |
| Morphology separation | מַלְכָּא is found via the Aramaic adapter and not_found via the Hebrew one (and vice versa for אֱלֹהִים); unsupported profile → unsupported_language |
| Retrieval tiers | Exact source → exact; diacritic-stripped → normalized; one word changed → no match (variant candidate at most); cross-profile lookups never match |
| Input validation | empty_upload, upload_too_large, unsupported_format (real GIF bytes), invalid_image, image_too_many_pixels each surface with their exact code |
| TSV parser | The recorded TSV fixture string parses to two reading-order lines with per-word confidences and the rounded mean (parser fixture — not OCR output, no accuracy claim) |
| Upload round-trip | Uploaded PNG bytes come back byte-identical from GET /api/uploads/{id}; unknown/traversal ids never serve a file |
| Correction flow | Garbled raw text + the fixture's corrected text translates via the corrected text; the response preserves both original_ocr_text and corrected_source_text |
| Model-required cases | OCR with the real Tesseract binary and real-artifact inference are marked model_required: deselected by `-m "not model_required"`, and where selected without prerequisites they skip naming the exact missing prerequisite |

### Full suites, the way CI runs them

```powershell
cd backend
python -m ruff check app tests
python -m compileall -q app tests
python -m pytest -q -m "not model_required"     # always-on CI equivalent
cd ..\frontend
npm ci; npm run typecheck; npm run test; npm run build
```
Expected: ruff clean; compile clean; backend suite passes with
model_required tests deselected (self-skipping tests report skipped
with reasons); frontend typecheck clean, vitest passes, production
build succeeds. The model-tests workflow (manual dispatch) provisions
Tesseract + the full corpus and runs the complete suite including
model_required, plus the evaluation harness in report-only mode.

### Offline one-command proof

```powershell
scripts\verify-offline.ps1            # bash: ./scripts/verify-offline.sh
```
Expected: the static scan passes, then the socket-blocked offline
tests pass; the script prints the optional manual Windows firewall
steps without executing them and needs no administrator rights.

### Retention maintenance

```powershell
cd backend
python -m app.maintenance --dry-run   # counts only
python -m app.maintenance             # performs the sweep
```
Expected: a JSON report with counts per store and bytes reclaimed;
dry-run changes nothing on disk or in the database.

### Performance smoke (measurements only)

```powershell
python training\evaluation\perf_smoke.py
```
Expected: a JSON report of measured stage timings for this machine,
with unavailable stages (e.g. OCR without the binary) recorded with
their honest status. No targets are stated or checked.

### Browser E2E (Playwright; not part of always-on CI)

Prerequisites and full instructions: frontend/e2e/README.md (backend
running with corpus imported, Tesseract provisioned, fixture images
generated, `npx playwright install chromium` once).

```powershell
cd frontend
npm run test:e2e
```
Expected: the Hebrew flow uploads the Genesis fixture, OCRs it,
translates to the corpus reference English, copies it, and downloads
ahaiet-result.json; the Aramaic flow selects the Aramaic profile
explicitly and shows Daniel 2:4's verified translation or the explicit
error state. Missing fixtures or unprovisioned OCR skip with the
prerequisite named.

## Historical record — foundation build (actually run at that time)
Recorded when the foundation was built, before the code-only instruction: backend pytest 15 passed; frontend typecheck clean; vitest 2 passed; Next.js build succeeded; live smoke: `/api/health` ok, real PNG upload 200, `/api/translate` honest 503. Tesseract was absent on that machine, so OCR was unavailable — that absence is what the OCR provisioning above addresses.

## Remediation regression cases (code review 2026-11-24) — NOT YET RUN

All cases below exist as code; none has been executed by the build
assistant. Run from the repo root unless stated.

Backend (from `backend/`): `python -m pytest tests/test_remediation.py -q`
- test_retrieval_duplicate_exact_is_ambiguous
- test_nodiac_collision_does_not_verify
- test_retrieval_cache_invalidated_cross_process
- test_variant_search_uses_token_index
- test_preserve_blank_lines
- test_process_all_segments_failed_terminal
- test_translate_all_segments_failed_is_422
- test_job_cancel_endpoint
- test_persist_results_disabled
- test_model_hash_mismatch_rejected
- test_model_card_path_escape_rejected
- test_missing_best_decoder_tries_second_same_profile
- test_decoder_empty_output_is_error / test_decoder_multiline_output_is_alignment_error
- test_ocr_timeout_returns_504
- test_highlight_second_repeated_word_only
- test_script_tier_requires_samples_and_dataset
- test_orientation_reports_not_applied_without_exif
- test_multipage_image_rejected
- test_config_validation_rejects_bad_values
- test_error_detail_is_sanitized
- test_rate_limiter_bounds_tracked_clients
- test_migration_is_transactional
- test_upload_write_is_atomic_and_conflict_checked
- test_fixture_manifest_is_canonical
- test_access_token_gates_reads
- test_translate_lineage_without_ocr_context

Training/evaluation (from repo root):
`python -m pytest training/tests/test_remediation_training.py -q`
- test_dictionary_lexicon_train_only
- test_zero_test_pairs_no_selection / test_one_test_pair_no_selection
- test_fallback_metric_is_chrf_not_chrf_pp
- test_selection_requires_comparable_runs
- test_clean_corpus_misalignment_fails / test_clean_corpus_counts_discards
- test_marian_checkpoint_selection_uses_best_evidence

Docs: `python backend/tests/check_docs_links.py` (exit 0 = all cited
paths resolve).

Frontend E2E (from `frontend/`): `npx playwright test e2e/remediation.spec.ts`
- test_switch_language_invalidates_translation (skips with the missing
  prerequisite when fixtures/OCR are absent)

Acceptance (provisioned machines only, from `backend/`):
`python -m pytest tests/test_real_pipeline_acceptance.py -q -m model_required`
- test_offline_full_real_pipeline (skips with the exact prerequisite
  when unprovisioned)

Windows smoke (test_windows_setup_smoke): on a Windows machine run
`scripts\setup-windows.ps1`, then `scripts\provision-ocr.ps1 -Install`,
then `scripts\start-backend.ps1` and confirm
`GET /api/capabilities` reports `ocr.tesseract.usable: true`. Not yet
executed anywhere.

## Re-review remediation cases (NEW-01..NEW-27) — coded, NOT YET RUN

Backend (from `backend/`): `python -m pytest tests/test_rereview.py -q`
- NEW-04: test_readiness_labels_single_evaluated_engine
- NEW-14: test_readiness_metric_without_run_record_is_not_evaluated
- NEW-08: test_cross_profile_verified_plus_ambiguous_requires_choice
- NEW-09: test_multiline_single_segment_uses_passage_flow,
  test_single_line_keeps_direct_path (exact blank-line equality)
- NEW-10: test_all_engines_timeout_gives_504_with_attempts,
  test_all_engines_unavailable_gives_503_not_model_not_provisioned,
  test_mixed_timeout_and_unavailable_gives_most_severe
- NEW-12: test_token_guard_matrix (401 without/with wrong token,
  non-401 with the configured token, across process, job
  read/result/cancel, history read/delete, uploads read)
- NEW-15: test_recovery_fails_only_stale_heartbeat_jobs (two
  JobManager instances; only the stale-heartbeat job is failed)
- NEW-16: test_job_ocr_deadline_terminates_hanging_worker (a
  list-langs-answering but otherwise hanging Tesseract double; the
  job ends failed with ocr_timeout well inside the adapter timeout)
- NEW-17: test_tier_validated_for_production_when_all_gates_hold,
  test_tier_high_cer_blocks_production (CER 0.45),
  test_tier_absent_script_identity_blocks_production,
  test_tier_fake_dataset_hash_blocks_production,
  test_tier_too_few_samples_blocks_production
- NEW-20: test_tesseract_probe_failure_not_usable_despite_traineddata
- NEW-21: test_tsv_offsets_slice_back_to_words (repeated, punctuated
  words; offsets slice back exactly)
- NEW-23: test_grapheme_clusters_keep_niqqud_with_base_letters
- NEW-27: test_verify_artifacts_catches_same_size_edit_with_restored_mtime
- NEW-18: test_languages_status_reflects_corpus
- NEW-26: `python -m pytest tests/test_docs_consistency.py -q`
  (books, split counts, model statuses, security controls vs docs)

Updated existing cases: tests/test_remediation.py
test_preserve_blank_lines now asserts exact strings (NEW-25);
test_translate_lineage_original_null_without_ocr uses a real
fixture-corpus match and asserts 200 + lineage fields (NEW-25);
the same-profile fallback test uses a command-vector double (NEW-05).

Training (from repo root):
`python -m pytest training/tests/test_remediation_training.py -q`
- NEW-04: test_selection_single_qualified_engine_labelled,
  test_selection_one_qualified_one_stale_competitor,
  test_selection_head_to_head_when_two_share_signature
  (replacing test_selection_requires_comparable_runs)
- NEW-01/NEW-02: test_group_integrity_mixed_language_daniel,
  test_group_integrity_still_catches_same_profile_span,
  test_prepare_run_mixed_corpus_counts

Frontend E2E (from `frontend/`): `npx playwright test e2e/race.spec.ts`
- NEW-06: "stale translate response is discarded after an edit"
  (route interception; the delayed response resolves after an edit
  and is never published; a fresh request publishes)
- NEW-07: "starting OCR supersedes previous output and disables
  translation"

Acceptance (provisioned machines only, from `backend/`):
`AHAIET_RELEASE_GATE=1 python -m pytest tests/test_real_pipeline_acceptance.py -q -m model_required`
- test_offline_full_real_pipeline_hebrew and
  test_offline_full_real_pipeline_aramaic (NEW-24): the corpus is
  provisioned from the committed fixture passages as an explicit
  step; the UNCORRECTED OCR output must pass CER <= 0.35 /
  WER <= 0.50 against the fixture ground truth before the
  correction/translation assertions; release-gate mode turns every
  prerequisite skip into a failure.
- test_ocr_quality_gate_rejects_wrong_output (unit-level; runs
  anywhere, no provisioning needed)
