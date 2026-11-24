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

## Contracts that must stay stable
- API responses stay backwards-compatible; new fields are additive. Errors remain {error:{code,message,detail}}.
- Raw OCR, corrected text, and normalized search keys remain separate representations; normalization lives in services/language/normalize.py.
- Biblical Aramaic in Hebrew script is never classified as Hebrew from script alone; language suggestion still returns "uncertain" without user selection or corpus evidence.
- Schema changes only as new MIGRATIONS entries in backend/app/storage/db.py (v1 foundation, v2 corpus fields + corpus_words).
- Corpora and model binaries stay outside source control; manifests carry checksums + provenance.
- A reference translation is returned only for a verified, identified corpus match; no gloss or paraphrase is ever substituted.

## Blockers
- Tesseract binary not provisioned on the build machine (stale apt lists; exact errors recorded in docs/BUILD_STATE.md and artifacts/manifests/models.json). heb/eng traineddata are downloaded. OCR-run tests skip with a reason until the binary exists; the measurement script then produces the first real CER/WER.

## Exact commands for the developer
See docs/VERIFICATION.md (setup, full test suites, per-case expected behaviour, OCR measurement, corpus import) and the README quickstart.

## Next work (when the owner sends it)
- Run the developer test pass and the OCR measurement; record real CER/WER and failure examples in docs/BUILD_STATE.md.
- General translation models (Moses SMT baseline and Marian NMT, evaluated per profile) for text with no corpus match.
- Kraken historical-script model evaluation if a suitable model is obtained.
