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
REGISTRY = FIXTURES / "manuscript_registry.json"


def _score_one(image: Path, ground_truth: str, language: str, label: str,
               stratum: str | None) -> dict:
    result = run_ocr(image, settings, language)
    scores = evaluate(ground_truth, result["original_ocr_text"])
    print(label, scores)
    return {"image": image.name, "reference": label,
            "language": language, "stratum": stratum, "scores": scores,
            "mean_confidence": result["mean_confidence"],
            "uncertain_span_count": len(result["uncertain_spans"]),
            "ground_truth": ground_truth,
            "ocr_output": result["original_ocr_text"]}


def _stratified(results: list[dict]) -> dict:
    """Per-stratum CER/WER means (AHAIET-052): synthetic fixtures are
    one stratum; real manuscript entries are reported by their own
    script/diacritics/degradation stratum, never blended into the
    synthetic figure."""
    groups: dict[str, list[dict]] = {}
    for r in results:
        groups.setdefault(r.get("stratum") or "synthetic_rendered", []).append(r)
    out = {}
    for name, rows in groups.items():
        cers = [r["scores"]["cer"] for r in rows if r["scores"].get("cer") is not None]
        wers = [r["scores"]["wer"] for r in rows if r["scores"].get("wer") is not None]
        out[name] = {"count": len(rows),
                     "cer_mean": round(sum(cers) / len(cers), 4) if cers else None,
                     "wer_mean": round(sum(wers) / len(wers), 4) if wers else None}
    return out


def main() -> int:
    truth = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    results = []
    for fx in truth["fixtures"]:
        results.append(_score_one(FIXTURES / fx["image"], fx["ground_truth"],
                                  fx["language"], fx["reference"],
                                  "synthetic_rendered"))
    # Real manuscript entries (AHAIET-052): scored only when the
    # registry actually carries rights-cleared, expert-annotated
    # entries; the shipped registry is empty and adds nothing.
    if REGISTRY.exists():
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for entry in registry.get("entries", []):
            image = FIXTURES / entry["image"]
            if not image.exists():
                print(f"registry entry {entry.get('id')}: image missing, skipped")
                continue
            results.append(_score_one(image, entry["ground_truth"],
                                      entry["language_profile"], entry["id"],
                                      entry.get("stratum")))
    out = FIXTURES / "ocr_measurement.json"
    out.write_text(json.dumps({"fixtures": results,
                               "stratified": _stratified(results)},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
