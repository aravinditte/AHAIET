# Limitations (Part 1, stated plainly)
- OCR does not run on a machine without Tesseract (or Kraken): the endpoints return 503 by design. No OCR output has ever been fabricated.
- Translation does not run: no Moses/Marian artifact exists. No dictionary gloss, example sentence, or reference translation is returned as a translation.
- reference_passages table is EMPTY: no scholarly corpus has been licensed/loaded, so no reference matching exists yet.
- Language identification returns "uncertain" without a user selection; there is no corpus/morphology evidence engine yet.
- Morphology, retrieval, and verification services are typed interfaces reporting not_provisioned.
- OpenCV is optional; without it, Pillow preprocessing is used and capabilities say so.
- No accuracy/confidence/benchmark numbers are claimed anywhere: nothing has been measured yet.
- Upload retention (AHAIET_RETENTION_DAYS, default 30) is configuration only in Part 1; no sweeper job runs yet.
- Single-user local app: no auth, not hardened for public deployment.
