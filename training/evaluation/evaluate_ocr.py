"""Measure OCR quality on the rendered fixtures with the real engine.

Runs the backend's own OCR service (preprocessing + Tesseract TSV) on
every fixture image and reports the measured CER/WER against ground
truth, plus the raw OCR output, in a JSON report. No number exists until
someone runs this with a provisioned Tesseract binary.

Run (from backend/, with Tesseract provisioned):
  AHAIET_TESSERACT_CMD=/path/to/tesseract TESSDATA_PREFIX=/path/to/tessdata \
    .venv/bin/python ../training/evaluation/evaluate_ocr.py
Writes training/ocr/fixtures/ocr_measurement.json.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.core.config import settings  # noqa: E402
from app.evaluation.metrics import evaluate  # noqa: E402
from app.services.ocr.service import run_ocr  # noqa: E402

FIXTURES = REPO / "training" / "ocr" / "fixtures"

def main() -> int:
    truth = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    results = []
    for fx in truth["fixtures"]:
        image = FIXTURES / fx["image"]
        result = run_ocr(image, settings, fx["language"])
        scores = evaluate(fx["ground_truth"], result["original_ocr_text"])
        results.append({"image": fx["image"], "reference": fx["reference"],
                        "language": fx["language"], "scores": scores,
                        "mean_confidence": result["mean_confidence"],
                        "uncertain_span_count": len(result["uncertain_spans"]),
                        "ground_truth": fx["ground_truth"],
                        "ocr_output": result["original_ocr_text"]})
        print(fx["reference"], scores)
    out = FIXTURES / "ocr_measurement.json"
    out.write_text(json.dumps({"fixtures": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
