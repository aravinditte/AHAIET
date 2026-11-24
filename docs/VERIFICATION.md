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

## Historical record — foundation build (actually run at that time)
Recorded when the foundation was built, before the code-only instruction: backend pytest 15 passed; frontend typecheck clean; vitest 2 passed; Next.js build succeeded; live smoke: `/api/health` ok, real PNG upload 200, `/api/translate` honest 503. Tesseract was absent on that machine, so OCR was unavailable — that absence is what the OCR provisioning above addresses.
