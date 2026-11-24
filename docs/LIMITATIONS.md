# Limitations (stated plainly)
- OCR does not run on a machine without a Tesseract binary (or a provisioned Kraken model): the endpoints return 503 by design. The build machine has the traineddata but not the binary (see docs/BUILD_STATE.md). No OCR output has ever been fabricated, and no CER/WER score exists yet — the measurement tooling is written but unrun.
- General translation does not exist yet: text that does not match an imported corpus passage gets an honest 503. Only verified corpus matches return English (the cited WEB text). No dictionary gloss, example sentence, or paraphrase is ever returned as a translation.
- The corpus covers Genesis and Daniel only, and five verses have no aligned English (WLC/WEB numbering differences, listed in docs/DATASETS.md).
- Morphology is lookup over the imported corpus word index: words outside Genesis/Daniel return not_found, and Daniel 2:4's Hebrew opening words are flagged Hebrew inside an Aramaic-range verse (that is what the source data says).
- Language identification returns "uncertain" without a user selection; suggestion from corpus/morphology evidence is not implemented.
- OpenCV is optional; without it, the Pillow/NumPy preprocessing pipeline is used and capabilities say so.
- Upload retention (AHAIET_RETENTION_DAYS, default 30) is configuration only; no sweeper job runs yet.
- Single-user local app: no auth, not hardened for public deployment.
