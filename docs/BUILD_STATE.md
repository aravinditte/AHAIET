# BUILD STATE — AHAIET
Current work: **Foundation monorepo + OCR and corpus retrieval + SMT/NMT training, evaluation, and backend integration + hybrid verification, complete passages, Kraken historical recognition, and performance instrumentation + security/offline/release hardening + two code-review remediation rounds (the 56-finding review and the re-review, findings NEW-01..NEW-27) — all code complete. Test/training/evaluation execution belongs to the developer (see docs/VERIFICATION.md); the only executions by the build assistant are the foundation test run recorded in docs/VERIFICATION.md, syntax checks, and corpus data-preparation parses whose counts are recorded in artifacts/manifests/datasets.json.**
Naming rule for this repository: work is named, never numbered. Do not introduce stage/sequence numbering in files, docs, comments, manifests, or commit messages. (Review findings are referenced by their NEW-NN ids for traceability; that is finding naming, not work sequencing.)

## Feature status
| Feature | Status | Notes |
|---|---|---|
| Monorepo scaffold, backend API shell, upload validation/storage, frontend upload/preview/RTL editor/export | done, test-run during the foundation build | recorded results in docs/VERIFICATION.md (historical section) |
| Preprocessing pipeline (conservative + enhanced profiles, step report, original preserved) | coded | Pillow/NumPy: EXIF, grayscale, adaptive contrast, bounded deskew, guarded median, upscale. NEW-22: Image.MAX_IMAGE_PIXELS is set once at startup; per-request pixel ceiling is explicit in validation; derived-memory budget refuses over-budget images with a structured error; the enhanced median is decided by a downscaled classifier pass |
| Tesseract OCR (TSV confidences, uncertain spans with authoritative character offsets, reading order, empty-result error) | coded; engine data partially provisioned | heb + eng traineddata downloaded (checksums in models.json); Tesseract binary NOT provisioned on the build machine (see Blockers). NEW-20: a failed --list-langs probe reports probe_failed and usable=false even when traineddata files are present. NEW-21: tokens and uncertain spans carry code-point offsets (offset_encoding="unicode_code_points") |
| Kraken adapter (historical recognition) | coded, unavailable | real integration: detection + version, version-tolerant blla segmentation + rpred recognition over manifest checkpoints, incompatible installs reported; NEW-23: confidence alignment uses grapheme clusters (combining-aware), and reports confidence_unavailable when counts cannot be reconciled; no Kraken package or checkpoint provisioned, so it reports unavailable with the reason |
| Script support matrix (GET /api/scripts) | coded | computed live; NEW-17 tiers: engine_installed / operational / evaluated_on_dataset / validated_for_production, each row carrying its unmet_conditions; validated_for_production requires script identity equal to the profile id, a recomputed-and-matching dataset hash, >= 50 samples, CER <= 0.20 and a recorded WER, and a checkpoint hash match; hebrew_square follows the Tesseract probe (operational at best); all four historical profiles unsupported with the missing evidence named |
| Candidate verification service | coded; not run | deterministic checks (coverage from corpus lemma evidence, omission/addition risk, named entities, numbers via a documented lexicon, negation counts, morphology-backed grammar observations, reference agreement, measured-only uncertainty); statuses never claim correctness; wired into /api/translate and /api/process as an additive verification field + provenance block |
| Complete passages | coded; not run | line segmentation preserving blank lines/order (NEW-09: any input with line boundaries takes the passage flow, even with one nonblank segment; blank-line positions preserved exactly), per-line routing, completed/partial/failed statuses, per-segment results, configurable max segments + total length; /api/process uses the same path |
| Reference-first routing refinement | coded; not run | evaluated trained engine beats unevaluated; NEW-08: cross-profile evidence (verified in one profile + ambiguous in another) requires an explicit profile choice; NEW-10: when engines existed but all failed, the categorized error is preserved (all-timeout -> 504 translation_timeout with per-engine attempt records; all-unavailable -> 503), never a fall-through to model_not_provisioned |
| Kraken training + HTR evaluation code | coded; not run | training/ocr/train_kraken.py; training/evaluation/evaluate_htr.py (CER/WER, records dataset_sha256 over the evaluation set — NEW-17 evidence). No checkpoint, no labelled data, no scores exist |
| Performance instrumentation + caches | coded; not run | core/timing.py StageTimer; stage_timings_ms on /api/ocr, /api/translate, /api/process and job results; translation cache (trained-model outputs only); retrieval in-process LRU invalidated by the corpus importer and by corpus revision |
| Corpus importer (morphhb/WLC Genesis + Daniel + Ezra + Ruth, WEB alignment) | coded; source data downloaded and parsed as data preparation | current parse report recorded in artifacts/manifests/datasets.json: 2,255 verses, 2,250 aligned English, Hebrew 1,988 / Aramaic 267, 0 duplicates, 0 validation errors; DB import is a developer-run step (scripts/import-corpus.*) |
| Reference retrieval (exact / normalized / variant-candidate, per-profile indexes) | coded | variant is never returned as a match or a translation; ambiguous normalized matches return candidates + 422, never a silent verified match |
| Verified-reference translation via /api/translate | coded | returns the cited edition's English only on a verified match; otherwise honest errors distinguishing no-match from no-corpus |
| Morphology (separate Hebrew / Aramaic adapters over the morphhb word index) | coded | found / not_found per word; no fabricated tags; 503 when the corpus is not imported |
| OCR fixtures + CER/WER measurement tooling | coded; not run | training/ocr/generate_fixtures.py, training/evaluation/evaluate_ocr.py, backend/app/evaluation/metrics.py; ground truth = real corpus text (Genesis 1:1, Daniel 2:4); NEW-24: the acceptance test scores uncorrected OCR against this ground truth with CER/WER gates |
| Frontend OCR/corpus wiring | coded | preprocessing selector, offset-based uncertain-span highlighting (approximate highlighting is labelled when offsets are absent), OCR profile note, citation/provenance panel, export payload = corrected text if nonempty else raw OCR (NEW-19); NEW-06/07: input-fingerprint race guards and OCR supersession; NEW-11: optional access token kept only in sessionStorage, preview via authenticated Blob fetch |
| Parallel-corpus preparation (per-profile splits, views, leakage checks, dataset cards) | coded; data-prep run recorded | training/datasets/prepare_parallel.py + canonical tokenizer; group integrity keyed by (language_profile, book, chapter) (NEW-01); current pairs — Hebrew train 906 / validation 996 / test 85, Aramaic train 67 / validation 46 / test 150 (NEW-02 split: Ruth held out as the Hebrew test book; Daniel Aramaic ch. 2 validation, chs. 3–7 test). Leakage checks passed over this assignment (see the manifest's import_report) |
| Moses SMT training pipeline (tokenize → clean → KenLM LM → train-model.perl → MERT → export + model card) | coded; not run | training/smt/train_smt.py; WSL2-first (scripts/smt-train.ps1); NEW-13: exported moses.ini carries absolute paths and export verification resolves references from an unrelated cwd; stops honestly when KenLM/Moses are missing or a profile has insufficient training pairs |
| Marian NMT training pipeline (data gate → joint SentencePiece vocab → Marian → export + model card) | coded; not run | training/nmt/train_nmt.py + CPU/GPU config templates; data gate minimum 500 train pairs: Hebrew passes (906), Aramaic (67) gets a not-ready report by design; decoder config exports absolute model/vocab paths (NEW-13) |
| Trained-model backend integration (real subprocess adapters, artifact resolution, per-profile selection, OOV/coverage) | coded; not run | adapters accept a command string, an shlex-split string, or a command VECTOR via config (NEW-05) and launch with cwd=artifact_dir (NEW-13); NEW-27: resolution cache serves only within the integrity TTL, verify_artifacts(force=True) rehashes content regardless of mtime/size, and startup re-verifies; NEW-14: a recorded score counts only with a valid evaluation-run record |
| Translation evaluation harness (dictionary gloss baseline, Moses, Marian, retrieval on the shared test split) | coded; not run | training/evaluation/evaluate_translation.py; sacrebleu chrF++/BLEU with labelled pure-Python fallback (fallback recorded as chrf, never chrf_pp); NEW-04: selection may pick a single qualifying engine labelled selection_basis="single_evaluated_engine", comparable=false; head_to_head requires >= 2 engines on the same run signature; NEW-14: each run archives prior metrics on EVERY engine card for the profile as stale |
| Translation models (Moses/Marian) | not provisioned | all four manifest entries status not_provisioned until a real training run exports an artifact |
| Background jobs (/api/process) | coded; not run | asynchronous (202 + polling + cancel) on a bounded executor; NEW-15: jobs carry owner_id + heartbeat_at (migration v5), startup recovery in the FastAPI lifespan fails only stale-heartbeat jobs and surfaces failures; NEW-16: job OCR runs in a subprocess worker bounded by the job deadline (ocr_timeout on expiry) |
| Training | none | nothing trained; no checkpoints, no metrics, no scores exist |

## Locally available artifacts (data, recorded at download time)
- morphhb OSIS: artifacts/corpora/morphhb/Gen.xml sha256 0526e5c9…d86449; Dan.xml sha256 bc69d0fa…18fc0d; Ezra.xml sha256 fb28ff69…7d0e; Ruth.xml sha256 fb6a2660…0a11e (CC BY 4.0 annotations; WLC public domain).
- WEB verse-per-line zip: artifacts/corpora/eng-web_vpl.zip sha256 88308b1c…4f4565c (public domain).
- Canonical parsed corpus: artifacts/corpora/passages.jsonl (2,255 passages, sha256 5ec1bc2f…ce69c, gitignored).
- Tesseract traineddata (outside the repo): heb sha256 7da6ea6b…3d3e1, eng sha256 daa0c97d…fc047 (Apache-2.0).
- Committed test fixture: training/datasets/fixtures/sample_passages.jsonl (6 real passages with provenance); OCR ground truth: training/ocr/fixtures/ground_truth.json (fixture PNGs are generated by the script).

## Blockers (exact)
- Tesseract binary: `apt-get download tesseract-ocr libtesseract4 libleptonica-dev libarchive13` on the build machine failed with "Unable to locate package" / "no candidate" against stale package lists; a following `apt-get update` did not complete and was stopped. Provisioning paths that remain: scripts/provision-ocr.ps1 (winget) on Windows, or a working apt/brew install — see docs/OCR.md. Consequence: OCR-run tests skip and no CER/WER exists yet. Nothing else is blocked: retrieval/morphology/translation-by-reference need only the corpus DB import.
- End-to-end acceptance (NEW-03) is blocked on the same provisioning: no real-pipeline run exists. The exact provisioned-machine acceptance sequence is recorded in docs/ACCEPTANCE_AUDIT.md.

## What was NOT run (per owner instruction)
Pytest, vitest, typecheck, build, and the OCR measurement for the OCR/corpus code were not executed by the build assistant. For the SMT/NMT training work, additionally: no training, no evaluation, and no inference were executed — the code was syntax-checked only (py_compile). The same applies to the hybrid verification / passages / Kraken / performance work, both remediation rounds, and the re-review remediation: all tests are coded only. docs/VERIFICATION.md lists every command and the expected behaviour per case for the developer run. Corpus downloads/parses as data preparation WERE run and their counts recorded (see the manifest import_report).

## Data facts the training code is built on (current parse, artifacts/manifests/datasets.json)
- Hebrew pairs: train 906, validation 996, test 85. Hebrew verses: train 906, validation 997 (1 without aligned English), test 85 (Ruth).
- Aramaic pairs: train 67 (Ezra only), validation 46 (Daniel ch. 2), test 150 (Daniel chs. 3–7; 154 verses, 4 without aligned English).
- Both profiles now have nonempty train/validation/test partitions (NEW-02). The Marian 500-pair gate remains unmet for Aramaic (67 pairs; ~267 Aramaic verses exist in the whole corpus) and is documented as such; verses are never duplicated to fill splits.
- Thresholds coded: Marian data gate minimum 500 training pairs (configurable, `--min-train-pairs`); SMT minimum 50 pairs (configurable, `--min-train-pairs`, `--allow-small` overrides); small-corpus statement threshold 1,000 training pairs in the dataset card.

## Security and release hardening (coded; not run)

| Area | State | Notes |
|---|---|---|
| Security middleware (headers, body ceiling, rate limits) | coded; not run | backend/app/core/security.py (pure ASGI): SecurityHeadersMiddleware, BodySizeLimitMiddleware, RateLimitMiddleware; wired in main.py; limits/origins via config env vars; tests as code in backend/tests/test_security.py |
| CORS restricted to configured local origins | coded; not run | default localhost:3000 + 127.0.0.1:3000; AHAIET_CORS_ORIGINS; never wildcard by default |
| Optional access token (NEW-12) | coded; not run | AHAIET_ACCESS_TOKEN; when set, _require_access guards uploads read, process submission, job read/result/cancel, and history read/delete; the frontend keeps the token only in sessionStorage and sends it as the X-AHAIET-Access-Token header (NEW-11) |
| Retention maintenance + CLI | coded; not run | backend/app/maintenance.py (`python -m app.maintenance [--dry-run] [--days N]`); optional startup sweep (default off); secure-delete = optional zero-overwrite before unlink, limits documented in docs/SECURITY.md |
| History opt-out | coded; not run | AHAIET_HISTORY_ENABLED=false → writes no-op, GET /api/history returns explicit disabled state; AHAIET_PERSIST_RESULTS is a separate switch governing job/result persistence |
| Logging audit | done (code audit) | backend runtime has no content-bearing logging; the only prints in the package are the setup-only corpus importer's counts/metadata output |
| Temp files | fixed | OCR scratch files now live under the configured storage area (settings.temp_dir) inside try/finally cleanup; job OCR worker request/result files likewise (NEW-16) |
| Dependency bounds + checker | coded; not run | upper bounds in backend/pyproject.toml + training/requirements.txt; scripts/check_dependencies.py (+ .ps1/.sh wrappers) compares installed versions from local metadata, no network |
| Offline self-check | coded; not run | backend/app/offline_check.py (`python -m app.offline_check`); allowlist = corpus importer + the checker itself; socket-blocked tests as code in backend/tests/test_offline.py; scripts/verify-offline.ps1/.sh |
| Tests as code | coded; not run | backend/tests/ (incl. test_rereview.py, test_docs_consistency.py), training/tests/, frontend unit tests; model_required pytest marker registered in pyproject; perf harness training/evaluation/perf_smoke.py (measurements only, no targets) |
| Browser E2E as code | coded; not run | frontend/e2e/ (Playwright config + Hebrew/Aramaic specs + remediation spec + race.spec.ts with route interception for NEW-06/07); @playwright/test devDependency + test:e2e script; NOT in always-on CI. E2E selectors aligned with the current page: the preview image in page.tsx carries data-testid="upload-preview", and translator.spec.ts / remediation.spec.ts use extract-button, translate-button and getByTestId("file-input") like race.spec.ts; every data-testid referenced in frontend/e2e/*.spec.ts exists in frontend/src (grep-verified) |
| CI workflows | written; not run | .github/workflows/ci.yml (always-on: ruff + compileall + pytest -m "not model_required"; frontend typecheck/vitest/build) and model-tests.yml (workflow_dispatch: Tesseract + corpus import + full suite + evaluation harness report-only). The GitHub App cannot push workflow files (403); the owner adds these two files manually via the web UI (see docs/PHASE_HANDOFF.md) |
| Docs | written | docs/SECURITY.md, OFFLINE_OPERATION.md, TROUBLESHOOTING.md, ACCEPTANCE_AUDIT.md, RELEASE.md; docs-to-manifest consistency guarded by backend/tests/test_docs_consistency.py (NEW-26) |
| Manifests | unchanged statuses | no entry became provisioned; tesseract-heb remains traineddata_downloaded_binary_missing; all translation/Kraken entries not_provisioned |

## Remediation build (code review of 2026-11-24) — code only, not run

All 56 findings of the first review were addressed in code (54 fixed; the real-pipeline acceptance findings remain scaffolding until a provisioned run exists). Per-finding status: docs/PHASE_HANDOFF.md. Highlights: Ezra added; book-group partitions; /api/process asynchronous; ambiguity-aware retrieval; comparability-gated selection; AHAIET_ACCESS_TOKEN introduced; DB migration v4.

## Re-review remediation (findings NEW-01..NEW-27) — code only, not run

All 27 re-review findings are addressed in code except NEW-03, which
remains an acceptance blocker by design (no provisioned machine, no
real run — see docs/ACCEPTANCE_AUDIT.md). Per-finding status:
docs/PHASE_HANDOFF.md (re-review section). Highlights:

- Splits redesigned (NEW-01/NEW-02): group integrity keyed by
  (language_profile, book, chapter); Ruth imported as the held-out
  Hebrew test book; Daniel Aramaic split ch. 2 validation / chs. 3–7
  test. New parse recorded above and in the manifest.
- Selection policy (NEW-04): single qualifying engine selectable,
  labelled single_evaluated_engine / comparable=false; metrics
  without run records ignored and stale metrics archived on every
  card (NEW-14).
- Decoder commands accept vectors, run with cwd=artifact_dir, and
  exports carry absolute paths (NEW-05/NEW-13); artifact integrity
  has an explicit forced verification (NEW-27).
- Frontend race guards, OCR supersession, sessionStorage token,
  export fallback (NEW-06/07/11/19); token guard matrix completed
  (NEW-12); /api/languages derives translation_status live (NEW-18).
- Jobs gained ownership/heartbeats and a deadline-bounded OCR
  subprocess (NEW-15/NEW-16); script tiers renamed and tightened
  (NEW-17); Tesseract probe honesty (NEW-20); token offsets
  (NEW-21); preprocessing global-state fix (NEW-22); Kraken
  grapheme-cluster confidence alignment (NEW-23).
- Tests strengthened: exact assertions, real-match lineage path,
  Playwright route-interception race specs, CER/WER-gated acceptance
  test with an explicit corpus-provisioning step and a release-gate
  mode (NEW-24/NEW-25); docs rewritten from the manifests with a
  consistency test (NEW-26).

## Superseded changelog (historic counts — do not cite as current)

- Parse of 2026-11-24 (Genesis + Daniel only): 1,890 verses, 1,885
  aligned English; Hebrew 1,690 / Aramaic 200. Splits then: Hebrew
  train 693 / validation 839 / test 157 pairs; Aramaic train 0 /
  validation 0 / test 196 pairs. Superseded by the Ezra parse.
- Parse of 2026-11-24 (Genesis + Daniel + Ezra): 2,170 verses, 2,165
  aligned English; Hebrew 1,903 / Aramaic 267. Splits then: Hebrew
  test partition empty; Aramaic validation empty. Superseded by the
  Ruth + Daniel-Aramaic chapter split recorded above (NEW-01/NEW-02).
- Script tier labels model_installed / experimentally_evaluated /
  production_supported: superseded by the NEW-17 tier names.
