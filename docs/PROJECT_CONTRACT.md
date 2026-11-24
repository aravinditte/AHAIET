# PROJECT CONTRACT — AHAIET
## Objective & flow
Upload a real image -> preprocess -> genuine local OCR -> raw captured source text -> user correction -> language profile -> real local translation -> complete English output -> copy/export. One evolving codebase across all build stages; never regenerate or replace working modules with mocks.
## Invariants (must not change silently)
1. Offline & free at runtime: no paid API/key, hosted translation/chatbot, runtime network inference, telemetry, or required cloud account. Locally provisioned free OCR/SMT/NMT models only.
2. Truthfulness: never fake OCR, translations, weights, datasets, scores, citations, readiness, or test results. Missing artifacts => status unavailable/blocked/unsupported with an actionable reason. A reference translation only for a verified, identified corpus match. No dictionary gloss presented as a complete translation.
3. Linguistic integrity: preserve raw Unicode, diacritics when recognized, word order, layout, RTL presentation, uncertainty markers. Raw OCR, corrected text, and normalized/search text are stored/displayed separately. Biblical Aramaic in Hebrew characters is NEVER classified as Hebrew from script alone. Edition/licence provenance retained. No claim of guaranteed 100% accuracy.
4. Security: validate upload content (not extensions); byte/pixel/resource limits; decompression-bomb guard; traversal-safe storage (hash names only); no sensitive source text in logs.
5. Compatibility: API contracts backwards-compatible; schema changes only via new entries in backend/app/storage/db.py MIGRATIONS. Corpora/model binaries stay outside source control; manifests carry checksums + provenance.
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
- OCR: both Hebrew-script profiles use the heb traineddata and record the profile used; Syriac traineddata is never substituted for Hebrew-script Aramaic. Uncertainty comes only from the engine's own TSV confidences.
## Naming and testing rules (owner)
- Name work only: no stage/sequence numbering in any file, doc, comment, manifest, test name, or commit message.
- The build assistant codes every case; test execution belongs to the developer. docs/VERIFICATION.md states what is coded, the commands, and the expected behaviour, and marks anything not yet run.
