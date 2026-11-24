# OCR
Baseline: Tesseract via subprocess (backend/app/services/ocr/tesseract_adapter.py). The adapter checks shutil.which("tesseract") (AHAIET_TESSERACT_CMD) and, when present, runs: tesseract <image> stdout -l heb --psm 6.
Install (Windows): UB-Mannheim Tesseract build, select Hebrew language data, or place heb.traineddata in tessdata. Verify: tesseract --list-langs shows heb. Then restart the backend; /api/capabilities will report tesseract available.
Specialized: Kraken adapter checks `import kraken`; a historical-script model must also be trained/provisioned (Part 2) — the import alone does not make historical OCR "ready".
Current state on the Part 1 build machine: `which tesseract` -> not found; OCR status = unavailable (verified in tests).
