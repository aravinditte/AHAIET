# Handoff — AHAIET (organised by work area)

- **Repository:** ~/workspace/ahaiet (GitHub: aravinditte/AHAIET). The foundation build sits on an earlier branch that the owner is retiring unmerged; the current tree (foundation + OCR/corpus work) is the source of truth and is to be pushed on a work-named branch.
- **Naming rule (owner, hard):** never write stage/sequence numbering anywhere — files, docs, comments, manifests, tests, commit messages. Name work only ("foundation", "OCR and corpus retrieval", …).
- **Testing rule (owner):** the build assistant codes every case; the developer runs the tests. docs/VERIFICATION.md carries the commands and expected behaviour for every case, marked as not-yet-run where applicable.

## Foundation (done, test-run at build time)
Monorepo (frontend/backend/training/scripts/artifacts/docs), FastAPI + SQLite migrations, content-validated upload + preview, all base endpoints, Next.js UI with RTL raw/corrected source separation, copy/export, PowerShell setup/start scripts. Recorded results are in docs/VERIFICATION.md (historical section).

## OCR and corpus retrieval (coded; developer runs the tests)
- **Preprocessing:** backend/app/services/preprocessing/service.py — conservative/enhanced profiles, EXIF/grayscale/adaptive contrast/bounded deskew/guarded median/upscale, step report, original preserved.
- **OCR:** services/ocr — Tesseract TSV adapter (word confidences -> uncertain_spans, mean_confidence, reading order), profile recorded per result, heb traineddata for both Hebrew-script profiles, Syriac never substituted, empty result -> 422 empty_transcription, missing engine -> 503. Kraken stays an honest check.
- **Corpus:** backend/app/corpus/import_morphhb.py — morphhb/WLC Genesis + Daniel parsed (1,890 verses), WEB aligned (1,885), language by documented Daniel range + morphhb H/A word flags, book-block partitions, dedup/validation, canonical JSONL + SQLite import (schema migration v2 adds passage fields + corpus_words). Data files gitignored; provenance + sha256 in artifacts/manifests/datasets.json. Six-passage committed fixture under training/datasets/fixtures/.
- **Retrieval:** services/retrieval — per-profile exact (diacritic-sensitive normalized key) and normalized (diacritic-insensitive) matching; high-overlap non-matches surface only as variant candidates with warnings, never as translations. Cross-profile search does not happen.
- **Translation:** /api/translate resolves verified corpus match -> cited WEB English (translation_method="verified_reference") -> provisioned model -> honest 503 distinguishing no-match vs no-corpus.
- **Morphology:** services/morphology + POST /api/morphology — separate Hebrew/Aramaic adapters over corpus_words filtered by profile AND word-level language; found/not_found per word; 503 corpus_unavailable when unimported.
- **Evaluation tooling:** backend/app/evaluation/metrics.py (Levenshtein CER/WER), training/ocr/generate_fixtures.py (renders Genesis 1:1 + Daniel 2:4 from real corpus text; ground_truth.json committed), training/evaluation/evaluate_ocr.py (writes ocr_measurement.json when run with a provisioned binary). No scores exist yet — none were measured.
- **Frontend:** preprocessing profile selector; OCR result state (uncertain-span highlighting, mean confidence, profile note); translation panel shows method + citation/provenance + warnings; JSON/TXT export includes translation_method and source_references.

## SMT/NMT training, evaluation, and backend integration (coded; developer runs everything)
- **Dataset preparation:** training/datasets/prepare_parallel.py — per-profile parallel files from the canonical corpus JSONL, reusing the recorded group split (Hebrew train 693 / validation 839 / test 157 pairs; Aramaic train 0 / validation 0 / test 196 — all Aramaic is in the Daniel test partition). Vocalized (canonical) + consonantal (derived, labelled) source views; empty-English verses excluded and counted (5); exact/nodiac cross-split duplicates are hard failures, near-duplicates flagged; dataset_card.json + leakage_report.json per profile; small-corpus statement threshold 1,000 train pairs. Canonical tokenizer: backend/app/services/language/tokenize.py (training/datasets/tokenize.py is its CLI form) — training and inference share it.
- **Moses SMT:** training/smt/train_smt.py — prep → tokenize (Moses perl for English when MOSES_HOME set, repository tokenizer otherwise and always for the Hebrew-script source; substitutions logged) → clean → KenLM lmplz (missing KenLM = stop, never faked) → train-model.perl (GIZA++, phrase extraction, msd-bidirectional-fe reordering) → MERT on validation when available (skip recorded in the card otherwise) → export to artifacts/models/smt/<profile>/ (moses.ini rewritten to the artifact dir, phrase/reordering tables, LM, vocabulary.source.txt, model_card.json) and flip the manifest entry. Guards: 0 pairs → exit 4; below 50 pairs → exit 4 unless --allow-small. WSL2-first via scripts/smt-train.ps1; runtime needs no WSL2.
- **Marian NMT:** training/nmt/train_nmt.py + config templates (CPU + GPU variants per profile). Data gate first: below --min-train-pairs (default 500) → not_ready.json/.md in artifacts/models/nmt/<profile>/ + exit 3 (the expected Aramaic outcome: 0 training pairs). Joint SentencePiece vocabulary (one .spm for both sides, documented choice). --pretrained takes a local checkpoint only; nothing is downloaded. Export: model.npz + vocab.spm + generated decoder-config.yml + vocabulary.source.txt + model_card.json; manifest flipped after export.
- **Backend integration:** services/translation/model_artifacts.py resolves a manifest entry only when status + artifact dir + model card + every card file + engine essentials are present, naming missing pieces otherwise; evaluation state is derived from recorded chrF++ (card or manifest) — "evaluated" vs "trained_but_not_evaluated". moses_adapter/marian_adapter are real subprocess adapters (lazy vocab load + cache, shared tokenizer for Moses, configurable timeout, OOV warnings + coverage). selection.py: retrieval first (in service.py), then evaluated-by-chrF++, then Moses-before-Marian default; strictly per profile. /api/translate response gains engine/model_version/artifact_sha256/coverage (additive; verified_reference shape unchanged). /api/models enriches translation entries with live artifact state; /api/capabilities gains translation.per_profile.
- **Evaluation:** training/evaluation/evaluate_translation.py — dictionary gloss baseline (dictionary_baseline.py; lemma/Strong's glosses from the corpus word index, unknown words marked ⟦ ⟧, labelled "not a sentence translation" everywhere; morphhb has no English gloss strings, so this is a lexical floor), Moses + Marian through the backend adapter path, retrieval baseline with the same-corpus upper-bound caveat printed in every report. SacreBLEU + chrF++ via sacrebleu, labelled pure-Python fallbacks otherwise (text_metrics.py). Latency mean/p95, coverage, five worst failure examples per engine, unavailable engines listed with reasons and null scores. Selection record written into the winner's model card + manifest entry only from a real run. human_review_template.md ships blank.
- **Tests as code:** backend/tests/test_translation_models.py (artifact resolution complete/incomplete, selection priority, OOV, end-to-end translate with clearly-labelled echo test-double binaries, POSIX/WSL for the shebang fixtures), training/tests/test_prepare_parallel.py (group integrity, planted exact + pointing-only cross-split duplicates, empty-English counting, view checks, Aramaic small-corpus card), frontend export vitest case for engine fields.
- **Nothing trained, nothing measured:** no checkpoints, model cards, benchmark files, or scores exist. Manifest SMT/NMT entries remain not_provisioned and now carry the artifact-layout + model-card contract.

## Hybrid verification, complete passages, historical recognition, performance (coded; developer runs everything)
- **Verification:** services/verification/service.py — verify_candidate(db_path, source, candidate, profile, method, context) returns a VerificationReport: checks source_coverage (corpus lemma/Strong's-aligned English evidence from aligned verses vs candidate content words; uncovered tokens listed; not_applicable without a corpus), omission_risk / addition_risk (documented length bands + uncovered ratio; risk flags only), named_entities (morphhb Np proper nouns vs capitalised or corpus-attested renderings), numbers (documented lexicon in services/language/numbers_lexicon.json + digit forms, both directions), negation (Hebrew/Aramaic particle counts vs candidate markers), grammar_construct_state + grammar_definite_article (morphology-backed observations only; tense/aspect is not_applicable by design), reference_agreement (token overlap vs a supplied verified reference; divergence warns, never rejects; not_applicable for verified_reference outputs), empirical_uncertainty (only measured inputs: OCR mean confidence, retrieval match type, recorded model metrics). Overall status vocabulary: no_issues_found / warnings / high_risk — never "correct". Wired into /api/translate and /api/process; every success also carries a provenance block (engine, model id/version, artifact hash, evaluation state, dataset card hash, retrieval citation, cached).
- **Routing:** strict order in services/translation — verified exact/normalized match -> evaluated trained engine -> unevaluated trained engine (response flagged unevaluated_model + warning) -> honest unavailable. Variant candidates remain error-attached only.
- **Passages:** services/language/passage.py splits multiline input into line segments (blank lines preserved as structure), each routed independently; statuses completed/partial/failed; segments[] per line; limits AHAIET_MAX_SEGMENTS (64) / AHAIET_MAX_PASSAGE_CHARS (20000) with explicit error codes. /api/translate uses the passage path for multiline/over-length input; /api/process runs OCR then the same path, passing the OCR mean confidence as a measured uncertainty input.
- **Kraken:** services/ocr/kraken_adapter.py is a real integration (package + ketos detection with version; version-tolerant resolution of blla segmentation / load_any / rpred; KrakenIncompatible reported with the detected version; per-line text + confidences). Script registry in services/ocr/script_profiles.json; support computed by script_profiles.py: hebrew_square via Tesseract; historical profiles supported ONLY when artifacts/benchmarks/htr-eval-<profile>.json exists with a measured CER and a checkpoint_sha256 matching a manifest checkpoint file on disk for that profile. GET /api/scripts exposes the matrix; /api/capabilities ocr section carries kraken detail + the matrix; /api/ocr takes engine + script_profile and refuses unsupported combinations with 422 script_unsupported (no silent fallback). Manifest carries four per-script Kraken slots, all not_provisioned.
- **Training/evaluation code:** training/ocr/train_kraken.py (ketos train over <data-dir>/provenance.txt + train/ line pairs; --base-checkpoint fine-tune; exports checkpoint + training_card.json to artifacts/models/kraken/<profile>/ and flips the manifest entry) and training/evaluation/evaluate_htr.py (runs the backend adapter per line image, micro-averaged CER/WER via app.evaluation.metrics, writes the htr-eval record). Wrappers: scripts/provision-kraken.ps1/.sh, scripts/train-kraken.ps1/.sh (WSL2 route on Windows). Kraken is an optional backend extra (pyproject `kraken`) and a training/requirements.txt entry. No checkpoint, data, or scores exist.
- **Performance:** core/timing.py StageTimer; stage_timings_ms additive on /api/ocr, /api/translate, /api/process responses and job results; schema migration v3 adds jobs.stage_timings_json + translation_cache (key = sha256 of profile + normalized source + engine + artifact hash; consulted only for trained-model inference after retrieval misses; hits labelled cached with original provenance; AHAIET_TRANSLATION_CACHE=false disables). Retrieval lookup has an in-process LRU (512) invalidated by import_into_db after a corpus import.
- **Frontend:** VerificationPanel (checks + the plain-language "flags risks, does not prove correctness" note + measured inputs), ScriptsPanel (live matrix with reasons), TranslationPanel gains provenance line, partial banner, per-segment breakdown, collapsible stage timings; page gains OCR engine + script selectors fed by /api/scripts; export (TXT + JSON) includes the verification summary and provenance; types extended additively.
- **Tests as code:** backend/tests/test_hybrid.py (negation/number mismatch, fixture-corpus coverage, reference-agreement divergence, evaluated-beats-unevaluated + unevaluated flagging with echo test doubles, variant-never-translation, passage partial/completed/failed/limits, matrix default + test-local fabricated record support, Kraken honest/incompatible paths, cache labelling + retrieval-never-cached, process timings), training/tests/test_evaluate_htr.py (score aggregation on synthetic pairs, pair collection problems), frontend export vitest case. None of it has been run.

## Contracts that must stay stable
- API responses stay backwards-compatible; new fields are additive. Errors remain {error:{code,message,detail}}.
- Raw OCR, corrected text, and normalized search keys remain separate representations; normalization lives in services/language/normalize.py.
- Biblical Aramaic in Hebrew script is never classified as Hebrew from script alone; language suggestion still returns "uncertain" without user selection or corpus evidence.
- Schema changes only as new MIGRATIONS entries in backend/app/storage/db.py (v1 foundation, v2 corpus fields + corpus_words, v3 jobs.stage_timings_json + translation_cache).
- Verification never labels a translation "correct"; script support is computed from evaluation records + checkpoint hashes, never asserted in a registry, manifest, or doc.
- Corpora and model binaries stay outside source control; manifests carry checksums + provenance.
- A reference translation is returned only for a verified, identified corpus match; no gloss or paraphrase is ever substituted.

## Blockers
- Tesseract binary not provisioned on the build machine (stale apt lists; exact errors recorded in docs/BUILD_STATE.md and artifacts/manifests/models.json). heb/eng traineddata are downloaded. OCR-run tests skip with a reason until the binary exists; the measurement script then produces the first real CER/WER.
- Kraken package not installed and no historical-script checkpoint or labelled line data exists; every historical profile therefore computes as unsupported, by design, until provisioning + training + evaluation are run by the developer.

## Exact commands for the developer
See docs/VERIFICATION.md (setup, full test suites, per-case expected behaviour, OCR measurement, corpus import) and the README quickstart.

## Next work (when the owner sends it)
- Run the developer test pass and the OCR measurement; record real CER/WER and failure examples in docs/BUILD_STATE.md.
- Run dataset preparation, then Hebrew SMT training in WSL2 and the evaluation harness; record the first real chrF++/SacreBLEU and the selection record. Run the Marian data gate for Aramaic and keep its not-ready report as the honest state until Aramaic training data exists.
- Decide the Aramaic data question deliberately (import Ezra's Aramaic sections, or revise the split strategy) — the pipelines will not improvise around it.
- Run the hybrid test pass (backend/tests/test_hybrid.py, training/tests/test_evaluate_htr.py, frontend typecheck/vitest/build) and record actual results in docs/BUILD_STATE.md.
- If historical-script work proceeds: provision Kraken (WSL2), assemble provenance-documented line-level data for one script, train with training/ocr/train_kraken.py, evaluate with training/evaluation/evaluate_htr.py, and let the support matrix flip on the measured record alone.

## Security and release hardening — handoff notes

- **Security:** middleware in backend/app/core/security.py (headers on all responses incl. errors; body ceiling default = upload limit + 1 MiB; per-client fixed-window rate limits for uploads/OCR/translate/process, 429 + Retry-After). CORS origins come from AHAIET_CORS_ORIGINS (local defaults only). Threat model + logging policy (metadata only; the corpus importer CLI is the package's only print, counts only): docs/SECURITY.md.
- **Retention & privacy:** `python -m app.maintenance [--dry-run] [--days N]` sweeps uploads/history/jobs/cache older than AHAIET_RETENTION_DAYS; optional startup sweep flag (default off); optional zero-overwrite before unlink with its limits stated honestly in SECURITY.md. AHAIET_HISTORY_ENABLED=false disables history writes and makes GET /api/history return an explicit disabled state.
- **Offline:** `python -m app.offline_check` statically proves no outbound constructs outside the setup-only importer; backend/tests/test_offline.py proves the runtime paths with sockets blocked; scripts/verify-offline.ps1/.sh run both. Frontend audit: the only URL in frontend/src is the local API base default; Hebrew fonts are system/local; next.config fetches nothing.
- **Tests:** new suites backend/tests/test_text_processing.py, test_security.py, test_offline.py, test_integration.py — all as code, none run. Tests needing real binaries/artifacts are marked `model_required` (registered in backend/pyproject.toml); always-on CI deselects them. Perf harness: training/evaluation/perf_smoke.py (measurements only).
- **Browser E2E:** frontend/e2e/ (Playwright). Prerequisites in frontend/e2e/README.md; deliberately not in always-on CI. Minimal data-testids were added to page.tsx, SourceEditor, TranslationPanel, UploadPanel, ExportButtons; dropzone gained role/aria-label; :focus-visible styles added.
- **CI — ACTION MAY BE NEEDED:** .github/workflows/ci.yml and .github/workflows/model-tests.yml are written in the tree. If the GitHub App cannot push workflow files (a known GitHub restriction), add exactly these two files manually via the GitHub web UI (Add file → Create new file, path `.github/workflows/ci.yml` and `.github/workflows/model-tests.yml`, contents from the local tree). Until they are on GitHub, CI has not run and no CI result exists.
- **Docs:** docs/SECURITY.md, docs/OFFLINE_OPERATION.md, docs/TROUBLESHOOTING.md, docs/ACCEPTANCE_AUDIT.md (14 implemented / 5 blocked / 0 not yet implemented — blocked: OCR on this machine (Tesseract binary), trained/evaluated model (no training run; Aramaic also needs the data decision), metrics from real test sets (no evaluation run), Windows validation (not yet executed on Windows), offline OCR leg (same binary)), docs/RELEASE.md (v0.1.0 scope + readiness + full Windows sequence). Manifest statuses unchanged.
- **Next (owner-run):** the full verification pass in docs/VERIFICATION.md, then the still-open items from the sections above (OCR measurement once the binary exists, Hebrew SMT training + evaluation, Aramaic data decision).

## Remediation section — code review findings (AHAIET-001..056)

Status key: **fixed** = implemented in code (tests as code where the
finding names one); **scaffolding** = code complete, the named
prerequisite is external evidence only the developer can produce.

- AHAIET-001 fixed — retrieval returns all identities; ambiguous exact
  or diacritic-insensitive matches return candidates, never a verified
  translation; `text_match` vs `passage_identity_verified` separated.
- AHAIET-002 fixed — same mechanism for the nodiac collision case.
- AHAIET-003 fixed — canonical fixture manifest
  `training/ocr/fixtures/fixtures.json`; generator and Playwright both
  read it.
- AHAIET-004 fixed — dictionary baseline lexicon is train-partition
  only; split + corpus sha256 recorded in the report.
- AHAIET-005 fixed — `insufficient_test_data` gate (default minimum 10
  test pairs); selection refuses to write.
- AHAIET-006 fixed — evaluation-run records; comparability = identical
  test-set sha256 + metric signature; stale metrics ignored/flagged;
  fallback recorded as `chrf`, never `chrf_pp`.
- AHAIET-007 scaffolding — opt-in real-pipeline acceptance test coded
  (`backend/tests/test_real_pipeline_acceptance.py`, model_required);
  prerequisite: a provisioned machine (Tesseract + heb + a resolved
  artifact/corpus) and a developer run.
- AHAIET-008 fixed — Ezra imported as data preparation; book-group
  partitions; counts in docs/TRAINING.md and datasets.json. Daniel
  Aramaic stays test-only.
- AHAIET-009 fixed — async /api/process (202), bounded executor,
  state machine, cancel endpoint, job expiry, startup recovery.
- AHAIET-010 fixed — all-segments-failed ends jobs in terminal
  `failed`; `awaiting_translation` removed.
- AHAIET-011 fixed — all-segments-failed translate returns 422;
  partial stays 200.
- AHAIET-012 fixed — segmentation preserves blank-line slots;
  reassembly reproduces the layout.
- AHAIET-013 fixed — corpus revision in `corpus_meta`, bumped by the
  importer in its own process, part of every retrieval cache key.
- AHAIET-014 fixed — `passage_tokens` inverted index + shortlist cap
  (50) before Jaccard variant scoring.
- AHAIET-015 fixed — `persist_results` separated from
  `history_enabled`; ephemeral in-memory jobs with TTL; test asserts
  no text in SQLite.
- AHAIET-016 fixed — scheduled retention: scripts/install-retention-task.ps1
  + cron/systemd note; `maintenance_runs` records every sweep;
  last sweep exposed in capabilities.
- AHAIET-017 fixed — startup sweep failure logged structurally and
  surfaced as `retention.degraded` in capabilities.
- AHAIET-018 fixed — migrate() runs each migration in an explicit
  transaction with the version row; v1-v3 SQL unchanged; v4 added.
- AHAIET-019 fixed — artifact resolution recomputes SHA-256 + size for
  every card-listed file; mismatch/missing/escaping path -> unusable
  with reasons; resolution cached by manifest/file signature.
- AHAIET-020 fixed — selection returns an ordered engine list;
  same-profile fallback with per-engine warnings; never crosses
  profiles.
- AHAIET-021 fixed — empty decoder stdout -> `translation_empty_output`;
  multiline single-segment output -> `translation_output_alignment`
  (blank padding lines tolerated).
- AHAIET-022 fixed — Tesseract timeout/OSError/decode -> typed
  503/504; TSV integer validation -> `ocr_parse_error`; configured
  timeout used.
- AHAIET-023 fixed — Pillow MedianFilter replaces the 9-array stack.
- AHAIET-024 fixed — deskew scoring masked to the text region on a
  darkness map with paper-consistent fill.
- AHAIET-025 fixed — script tiers model_installed /
  experimentally_evaluated / production_supported with gates (finite
  CER in [0, 0.5], >= 20 independent samples by default, script match,
  dataset + checkpoint checksums).
- AHAIET-026 fixed — translate lineage: original_ocr_text raw-or-null,
  corrected_source_text separate, ocr_request_id accepted.
- AHAIET-027 fixed — translation invalidated on text/language/profile/
  preprocessing change; AbortControllers + monotonic request ids.
- AHAIET-028 fixed — uncertain spans carry index/occurrence_id/block/
  par/line_id; SourceEditor highlights by occurrence id.
- AHAIET-029 fixed — E2E split: honest-unsupported smoke specs +
  AHAIET_E2E_GATE=release acceptance specs that FAIL when fixtures or
  models are absent.
- AHAIET-030 scaffolding — same acceptance test as AHAIET-007 (the
  Windows half of the evidence is acceptance-audit criterion 18 /
  test_windows_setup_smoke: scripts reviewed, not executed on Windows).
- AHAIET-031 fixed — settings validators with clear startup errors;
  error sanitization (paths stripped, bounded) in adapters and the
  global error envelope.
- AHAIET-032 fixed — provision-ocr.ps1 -Install (winget install,
  --list-langs heb verification, fixture smoke OCR, persists
  ahaiet.local.env); start-backend.ps1 loads it; setup-windows.ps1
  accepts any Python 3.11+ via `py -3` chain and invokes the venv
  interpreter directly.
- AHAIET-033 fixed — global OCR/translation semaphores, per-job
  deadline across segments, queue-full 503 with Retry-After.
- AHAIET-034 fixed — readiness probe runs bounded TTL-cached
  `tesseract --list-langs`; binary_available /
  language_data_available / usable reported separately; panel updated.
- AHAIET-035 fixed — passage translation uses ONE decoder invocation
  per segment batch with strict line-count alignment; Kraken model
  cached per checkpoint hash (max 2).
- AHAIET-036 fixed — profile_choice_required (422) with candidate
  profiles + evidence when no profile is selected and evidence is
  ambiguous; single-profile evidence proceeds and states its basis.
- AHAIET-037 fixed — full decode in validation, warnings-as-errors,
  multipage/animation rejected for the single-image pipeline.
- AHAIET-038 fixed — decoded+intermediate byte budget enforced before
  heavy preprocessing steps.
- AHAIET-039 fixed — orientation step reports attempted vs applied
  from the EXIF tag; step renamed `pixel_upscale` with scaler +
  resolutions (report label change, noted in docs/API.md + OCR.md).
- AHAIET-040 fixed — TSV block/par/line ids retained in the OCR
  result structure (additive span fields).
- AHAIET-041 fixed — Kraken confidences: `confidence_unavailable`
  instead of fabricated zeros when unalignable; real segmentation
  geometry used when provided, else marked unavailable; kraken pin
  narrowed to >=4.3,<5.0 in the training extra.
- AHAIET-042 fixed — Literal profile/engine/preprocessing types,
  bounded fields, upload_id pattern, psm 0..13 in schemas.
- AHAIET-043 fixed — rate limiter prunes expired buckets, hard cap on
  tracked clients, X-Forwarded-For honoured only with
  AHAIET_TRUST_FORWARDED_FOR.
- AHAIET-044 fixed — upload writes are temp-file + fsync + os.replace
  with existing-file hash/size verification (409 on conflict).
- AHAIET-045 fixed — optional AHAIET_ACCESS_TOKEN gates upload reads +
  history; threat model updated in docs/SECURITY.md (hash id is a
  locator, not authorization; keep loopback binding).
- AHAIET-046 fixed — export/copy per-action disabled states; errors
  surfaced; object URLs revoked after a tick.
- AHAIET-047 fixed — readiness/scripts panels: manual refresh +
  refresh on window focus; new fields/tiers shown.
- AHAIET-048 fixed — Windows doubles `echo_decoder.cmd` alongside the
  POSIX script; tests pick by platform.
- AHAIET-049 fixed — clean_corpus asserts equal line counts and logs/
  counts every discarded pair with reason.
- AHAIET-050 fixed — SMT export resolves every moses.ini path inside
  the export dir, writes export_verification.json, fails loudly on
  unresolved refs.
- AHAIET-051 fixed — Marian checkpoint selection uses explicit
  evidence only (model.npz.best / validation-log best iteration);
  never lexical-last; fails without evidence.
- AHAIET-052 fixed — manuscript_registry.json (empty entries) +
  rights/annotation requirements + stratified evaluation support in
  evaluate_ocr.py. No images fabricated.
- AHAIET-053 fixed — ACCEPTANCE_AUDIT regenerated with the
  coded/unit_tested/integrated/end_to_end_tested/blocked/unsupported
  states, corrected paths (services/ocr/script_profiles.py,
  services/verification/service.py), and a docs link-check test as
  code (backend/tests/check_docs_links.py). Nothing is labelled
  end_to_end_tested.
- AHAIET-054 fixed — exact pins for direct backend dependencies (set +
  rationale in docs/RELEASE.md); pip-audit / npm audit scan steps
  added to the CI workflow files (which still need the repository
  owner's manual addition for the workflows permission).
- AHAIET-055 fixed — adapter/concurrency settings validated at
  startup (timeouts, workers, caps, TTLs all bounded).
- AHAIET-056 fixed — docs/PROVISIONING.md state machine with a
  verification command per state; capabilities exposes
  provisioning_state computed from live checks.
