# BUILD STATE — AHAIET
Current work: **Foundation monorepo (complete and test-run at build time) + OCR and corpus retrieval (code complete) + SMT/NMT training, evaluation, and backend integration (code complete; all test/training/evaluation execution delegated to the developer — see docs/VERIFICATION.md).**
Naming rule for this repository: work is named, never numbered. Do not introduce stage/sequence numbering in files, docs, comments, manifests, or commit messages.

## Feature status
| Feature | Status | Notes |
|---|---|---|
| Monorepo scaffold, backend API shell, upload validation/storage, frontend upload/preview/RTL editor/export | done, test-run during the foundation build | recorded results in docs/VERIFICATION.md (historical section) |
| Preprocessing pipeline (conservative + enhanced profiles, step report, original preserved) | coded | Pillow/NumPy: EXIF, grayscale, adaptive contrast, bounded deskew, guarded median, upscale. Developer-run tests: tests/test_corpus_ocr.py |
| Tesseract OCR (TSV confidences, uncertain spans, reading order, empty-result error) | coded; engine data partially provisioned | heb + eng traineddata downloaded (checksums in models.json); Tesseract binary NOT provisioned on the build machine (see Blockers) |
| Kraken adapter | coded, unavailable | honest import check; no model |
| Corpus importer (morphhb/WLC Genesis + Daniel, WEB alignment) | coded; source data downloaded and parsed once as data preparation | parse report: 1,890 verses, 1,885 aligned English, Hebrew 1,690 / Aramaic 200, 0 duplicates, 0 validation errors; DB import is a developer-run step (scripts/import-corpus.*) |
| Reference retrieval (exact / normalized / variant-candidate, per-profile indexes) | coded | variant is never returned as a match or a translation |
| Verified-reference translation via /api/translate | coded | returns the cited edition's English only on a verified match; otherwise honest 503 distinguishing no-match from no-corpus |
| Morphology (separate Hebrew / Aramaic adapters over the morphhb word index) | coded | found / not_found per word; no fabricated tags; 503 when the corpus is not imported |
| OCR fixtures + CER/WER measurement tooling | coded; not run | training/ocr/generate_fixtures.py, training/evaluation/evaluate_ocr.py, backend/app/evaluation/metrics.py; ground truth = real corpus text (Genesis 1:1, Daniel 2:4) |
| Frontend OCR/corpus wiring | coded | preprocessing selector, uncertain-span highlighting, OCR profile note, citation/provenance panel, export includes method + references |
| Parallel-corpus preparation (per-profile splits, views, leakage checks, dataset cards) | coded; not run | training/datasets/prepare_parallel.py + canonical tokenizer; splits reuse the recorded group strategy: Hebrew train 693 / validation 839 / test 157 pairs, Aramaic train 0 / validation 0 / test 196 (counts from the importer's parse data; the prep run itself is the developer's) |
| Moses SMT training pipeline (tokenize → clean → KenLM LM → train-model.perl → MERT → export + model card) | coded; not run | training/smt/train_smt.py; WSL2-first (scripts/smt-train.ps1); stops honestly when KenLM/Moses are missing or a profile has no/insufficient training pairs (Aramaic: 0 pairs → exit 4 explanation) |
| Marian NMT training pipeline (data gate → joint SentencePiece vocab → Marian → export + model card) | coded; not run | training/nmt/train_nmt.py + CPU/GPU config templates; data gate default minimum 500 train pairs: Hebrew passes, Aramaic (0 pairs) gets a not-ready report by design; fine-tuning from a local checkpoint only |
| Trained-model backend integration (real subprocess adapters, artifact resolution, per-profile selection, OOV/coverage) | coded; not run | adapters resolve manifest entries against disk + model cards and name missing pieces; selection = recorded chrF++ wins, else Moses before Marian; /api/translate gains engine/model_version/artifact_sha256/coverage (additive); /api/models and /api/capabilities report live artifact state incl. trained_but_not_evaluated vs evaluated |
| Translation evaluation harness (dictionary gloss baseline, Moses, Marian, retrieval on the shared test split) | coded; not run | training/evaluation/evaluate_translation.py; sacrebleu chrF++/BLEU with labelled pure-Python fallback; retrieval figure carries the same-corpus upper-bound caveat; writes the selection record into model cards + manifest only after a real run; human_review_template.md ships blank |
| Translation models (Moses/Marian) | not provisioned | manifest entries now describe the artifact layout + model-card contract; status stays not_provisioned until a real training run exports an artifact |
| Training | none | nothing trained; no checkpoints, no metrics, no scores exist |

## Locally available artifacts (data, recorded at download time)
- morphhb OSIS: artifacts/corpora/morphhb/Gen.xml sha256 0526e5c9…d86449; Dan.xml sha256 bc69d0fa…18fc0d (CC BY 4.0 annotations; WLC public domain).
- WEB verse-per-line zip: artifacts/corpora/eng-web_vpl.zip sha256 88308b1c…4f4565c (public domain).
- Canonical parsed corpus: artifacts/corpora/passages.jsonl (1,890 passages, gitignored).
- Tesseract traineddata (outside the repo): heb sha256 7da6ea6b…3d3e1, eng sha256 daa0c97d…fc047 (Apache-2.0).
- Committed test fixture: training/datasets/fixtures/sample_passages.jsonl (6 real passages with provenance); OCR ground truth: training/ocr/fixtures/ground_truth.json (fixture PNGs are generated by the script).

## Blockers (exact)
- Tesseract binary: `apt-get download tesseract-ocr libtesseract4 libleptonica-dev libarchive13` on the build machine failed with "Unable to locate package" / "no candidate" against stale package lists; a following `apt-get update` did not complete and was stopped. Provisioning paths that remain: scripts/provision-ocr.ps1 (winget) on Windows, or a working apt/brew install — see docs/OCR.md. Consequence: OCR-run tests skip and no CER/WER exists yet. Nothing else is blocked: retrieval/morphology/translation-by-reference need only the corpus DB import.

## What was NOT run (per owner instruction)
Pytest, vitest, typecheck, build, and the OCR measurement for the OCR/corpus code were not executed by the build assistant. For the SMT/NMT training work, additionally: no dataset-preparation run, no training, no evaluation, and no inference were executed — the code was syntax-checked only (py_compile). docs/VERIFICATION.md lists every command and the expected behaviour per case for the developer run.

## Data facts the training code is built on (from the importer's recorded parse)
- Hebrew: train 693, validation 840 (1 without aligned English → 839 pairs), test 157 (Daniel's Hebrew verses).
- Aramaic: all 200 passages are in the Daniel test partition (4 without aligned English → 196 test pairs); train 0, validation 0. Any Aramaic training requires a deliberate data decision (more Aramaic books, e.g. Ezra's Aramaic sections, or a revised split strategy) — the pipelines refuse rather than improvise.
- Thresholds coded: Marian data gate minimum 500 training pairs (configurable, `--min-train-pairs`); SMT minimum 50 pairs (configurable, `--min-train-pairs`, `--allow-small` overrides); small-corpus statement threshold 1,000 training pairs in the dataset card.
