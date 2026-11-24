# PROJECT CONTRACT — AHAIET
## Objective & flow
Upload a real image -> preprocess -> genuine local OCR -> raw captured source text -> user correction -> language profile -> real local translation -> complete English output -> copy/export. One evolving codebase across all build stages; never regenerate or replace working modules with mocks.
## Invariants (must not change silently)
1. Offline & free at runtime: no paid API/key, hosted translation/chatbot, runtime network inference, telemetry, or required cloud account. Locally provisioned free OCR/SMT/NMT models only.
2. Truthfulness: never fake OCR, translations, weights, datasets, scores, citations, readiness, or test results. Missing artifacts => status unavailable/blocked/unsupported with an actionable reason. A reference translation only for a verified, identified corpus match. No dictionary gloss presented as a complete translation.
3. Linguistic integrity: preserve raw Unicode, diacritics when recognized, word order, layout, RTL presentation, uncertainty markers. Raw OCR, corrected text, and normalized/search text are stored/displayed separately. Biblical Aramaic in Hebrew characters is NEVER classified as Hebrew from script alone. Edition/licence provenance retained. No claim of guaranteed 100% accuracy.
4. Security: validate upload content (not extensions); byte/pixel/resource limits; decompression-bomb guard; traversal-safe storage (hash names only); no sensitive source text in logs.
5. Compatibility: API contracts backwards-compatible; schema changes only via new entries in backend/app/storage/db.py MIGRATIONS. Corpora/model binaries stay outside source control; manifests carry checksums + provenance.
6. Runtime makes no network calls: the only code permitted to touch the network is the setup-only corpus importer under its explicit download flag (and package managers during installation). `python -m app.offline_check` must report no runtime findings; provisioning downloads happen only in the documented setup scripts/importer (docs/OFFLINE_OPERATION.md).
7. CI workflow files (`.github/workflows/ci.yml`, `.github/workflows/model-tests.yml`) may need manual addition via the GitHub web UI if the GitHub App cannot push workflow files; their absence from the repo is a known, documented state (docs/PHASE_HANDOFF.md), never a silent drop.
## Supported profiles
biblical_hebrew, biblical_aramaic (separate). Future (unsupported until models+corpora+evals exist): old_epigraphic_hebrew, paleo_hebrew, qumran_hebrew, old_aramaic, imperial_aramaic, jewish_palestinian_aramaic, jewish_babylonian_aramaic, classical_syriac.
## Stack decisions
Next.js+TS+React+Tailwind v4; Python 3.11+ FastAPI/Pydantic/Uvicorn; Pillow/NumPy, OpenCV optional-import; SQLite (stdlib sqlite3) initially, PostgreSQL migration path later; Tesseract baseline + Kraken adapter; Moses SMT + Marian NMT, best measured per profile wins; Windows PowerShell primary; CPU-only must work; WSL2/GPU/Docker optional.
## Readiness definitions
- ready/available: artifact exists on disk, is wired, and was exercised by a real check recorded in BUILD_STATE.md.
- blocked: implemented but a named external artifact/dependency is missing (e.g. tesseract binary).
- unsupported: no model/corpus/eval exists for that profile/feature; API says so explicitly.
A manifest placeholder entry is never evidence of readiness.
## Dataset/licence rules
See docs/DATASETS.md. No invented scholarly corpus entries, ever.
## Corpus, retrieval, and morphology decisions (stable)
- Canonical corpus: morphhb/WLC (Genesis, Daniel) + WEB alignment, imported by backend/app/corpus/import_morphhb.py; provenance and sha256 live in artifacts/manifests/datasets.json; data files stay out of source control.
- Language assignment: Daniel's documented Aramaic range (2:4b–7:28) at verse level, morphhb H/A morph-code prefixes at word level. Both are kept; neither is silently overridden by the other.
- Retrieval trust levels are distinct and labelled: exact (diacritic-sensitive) and normalized (diacritic-insensitive) are verified matches; anything else is at most a variant candidate with a warning, never a translation.
- Retrieval and morphology never cross language profiles. Hebrew morphology data is never applied to Aramaic words or vice versa.
- /api/translate order: verified corpus reference -> provisioned local model -> honest unavailable. The unavailable message distinguishes "corpus present, no match" from "no corpus imported".
- Trained-model readiness is derived, never asserted: a manifest entry counts only when its artifact directory, model card, every card-listed file, and the engine's essential pieces are present on disk; missing pieces are named in errors and in /api/models. "evaluated" requires a chrF++ value recorded by the evaluation harness in the model card or manifest; otherwise a complete artifact is "trained_but_not_evaluated".
- Engine selection per profile: verified retrieval first; among trained engines, the higher recorded chrF++ on the shared held-out test split wins when at least two engines share a run signature (selection_basis "head_to_head"); a single qualifying engine may be selected with the record labelled selection_basis "single_evaluated_engine", comparable=false; with no recorded metrics the default order is Moses SMT before Marian NMT. Selection is read from model cards/manifest records written by real runs — never hardcoded quality claims, and never carried across profiles.
- Training data integrity: splits are passage-group (book/chapter) blocks from the recorded strategy; exact or diacritic-insensitive duplicates across splits are hard failures; verses with empty aligned English are excluded and counted. The dictionary gloss baseline is labelled "not a sentence translation" wherever it appears and is never served to users as a translation. Retrieval scores on the corpus's own test split are always reported with the upper-bound caveat.
- Tokenization is single-sourced (backend/app/services/language/tokenize.py): training files and runtime inference use the same implementation; the vocalized view is canonical and diacritics are never stripped outside the explicitly labelled consonantal view.
- OCR: both Hebrew-script profiles use the heb traineddata and record the profile used; Syriac traineddata is never substituted for Hebrew-script Aramaic. Uncertainty comes only from the engine's own TSV confidences.
## Hybrid verification, passages, and historical recognition decisions (stable)
- Verification statuses are a closed vocabulary — checks report pass / warn / fail / not_applicable and reports conclude no_issues_found / warnings / high_risk. Nothing in the system ever labels a translation "correct"; the checks flag risks with evidence. Uncertainty fields come only from measured sources (OCR engine confidences, retrieval match type, harness-recorded model metrics) — no computed correctness percentage exists anywhere.
- Reference-first routing is strict: verified exact/normalized corpus match -> trained engine with harness-recorded evaluation metrics -> trained engine without recorded metrics (flagged unevaluated_model) -> honest unavailable. A normalized_variant candidate is never returned as a translation.
- Passages: multiline input is routed line by line and reassembled in order with blank lines preserved; untranslated lines stay visibly empty with per-segment errors — a segment is never fabricated to complete a passage. Segment and length limits are configuration, and exceeding them is an explicit error.
- Script support is computed, never declared: a historical script profile is supported only when a measured HTR evaluation record exists whose checkpoint hash matches a checkpoint file on disk for that profile. Registry files, manifests, and docs may not assert support directly. OCR engine routing never substitutes silently across scripts.
- The translation cache serves trained-model outputs only, keyed by profile + normalized source + engine + artifact hash; verified retrieval is always consulted first and is never served from the cache; cache hits are labelled cached with the original provenance. A configuration flag disables the cache.
- Stage timings are measurements of this machine only; no latency target or expected duration is stated anywhere.

## Naming and testing rules (owner)
- Name work only: no stage/sequence numbering in any file, doc, comment, manifest, test name, or commit message.
- The build assistant codes every case; test execution belongs to the developer. docs/VERIFICATION.md states what is coded, the commands, and the expected behaviour, and marks anything not yet run.

## Remediation invariants (code review, 2026-11-24)

- **Ambiguity is never verified.** A retrieval key that identifies
  more than one passage — or a diacritic-insensitive key spanning
  differing vocalized forms — returns candidates with reason
  `ambiguous_match`, never a translation presented as verified.
  `text_match` and `passage_identity_verified` are separate facts.
- **Evaluation comparability.** A score exists only with its
  evaluation-run record (test-set sha256, sample count, metric
  signature, artifact sha256, date). Head-to-head comparison uses
  only identical test-set + signature runs; a single qualifying
  engine may still be selected, labelled non-comparable (see the
  selection rule above); stale scores are archived on every card for
  the profile and flagged; an empty/below-minimum test partition is
  `insufficient_test_data` and writes no selection.
- **Job state machine.** /api/process jobs move only
  queued -> running_ocr -> running_translation ->
  completed | partial | failed | cancelled (plus `expired` for
  TTL-expired terminal results). Every job ends in a terminal state;
  there is no awaiting/non-terminal end state.
- **Profile honesty.** Translation never silently crosses profiles:
  fallback is ordered within one profile, and ambiguous profile
  evidence without a user selection is a structured
  `profile_choice_required` response.
