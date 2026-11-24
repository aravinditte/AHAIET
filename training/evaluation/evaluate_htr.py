"""Measure a Kraken checkpoint on a labelled line-level test set.

Runs the backend Kraken adapter on every line image in the test
directory (each image has a same-stem .txt ground-truth transcript),
aggregates CER/WER from raw edit distances, and writes the evaluation
record that the backend's script support matrix reads:

    artifacts/benchmarks/htr-eval-<script-profile>.json

The record carries the checkpoint's sha256; the support matrix marks
the profile supported only while a checkpoint file with that exact
hash is present on disk. Scores exist only after a real run of this
script — nothing here estimates or pre-fills them.

Run (from repo root, Kraken installed, checkpoint trained):
  python training/evaluation/evaluate_htr.py \
      --profile paleo_hebrew \
      --checkpoint artifacts/models/kraken/paleo_hebrew/model.mlmodel \
      --test-dir /path/to/ground-truth/test
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from app.evaluation.metrics import levenshtein  # noqa: E402
from training.common.manifest import sha256_file, write_json  # noqa: E402

IMAGE_SUFFIXES = (".png", ".tif", ".tiff", ".jpg", ".jpeg")


def collect_test_pairs(test_dir: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    pairs, problems = [], []
    if not test_dir.is_dir():
        return [], [f"test directory does not exist: {test_dir}"]
    for path in sorted(test_dir.iterdir()):
        if path.suffix.lower() in IMAGE_SUFFIXES:
            transcript = path.with_suffix(".txt")
            if not transcript.is_file():
                problems.append(f"image without transcript: {path.name}")
            else:
                pairs.append((path, transcript.read_text(encoding="utf-8").strip()))
    if not pairs and not problems:
        problems.append(f"no line images found in {test_dir}")
    return pairs, problems


def dataset_sha256(test_dir) -> str:
    """Hash of the labelled evaluation dataset (NEW-17): sha256 over
    the sorted relative paths and bytes of every file under the test
    directory. backend/app/services/ocr/script_profiles.py recomputes
    exactly this to verify an evaluation record."""
    import hashlib as _h
    root = Path(test_dir)
    h = _h.sha256()
    if root.is_file():
        return _h.sha256(root.read_bytes()).hexdigest()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(root)).encode("utf-8"))
            h.update(path.read_bytes())
    return h.hexdigest()


def compute_htr_scores(pairs: list[tuple[str, str]]) -> dict:
    """Aggregate CER/WER over (reference, hypothesis) text pairs.

    Aggregation is by summed edit distance over summed reference length
    (micro-average), so long lines weigh proportionally — the standard
    way OCR benchmarks report a corpus-level rate."""
    char_dist = char_total = word_dist = word_total = 0
    for reference, hypothesis in pairs:
        char_dist += levenshtein(list(reference), list(hypothesis))
        char_total += len(reference)
        word_dist += levenshtein(reference.split(), hypothesis.split())
        word_total += len(reference.split())
    return {
        "cer": round(char_dist / char_total, 4) if char_total else 0.0,
        "wer": round(word_dist / word_total, 4) if word_total else 0.0,
        "lines": len(pairs),
        "reference_chars": char_total,
        "reference_words": word_total,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate a Kraken checkpoint on labelled line data")
    ap.add_argument("--profile", required=True, help="script profile id (e.g. paleo_hebrew)")
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--test-dir", type=Path, required=True,
                    help="directory of line images with same-stem .txt transcripts")
    ap.add_argument("--out", type=Path, default=None,
                    help="output record path (default artifacts/benchmarks/htr-eval-<profile>.json)")
    args = ap.parse_args(argv)

    if not args.checkpoint.is_file():
        print(f"ERROR: checkpoint not found: {args.checkpoint}")
        return 2
    pairs, problems = collect_test_pairs(args.test_dir)
    if problems:
        print("ERROR: test data problems:\n  " + "\n  ".join(problems))
        return 2

    from app.services.ocr import kraken_adapter
    if not kraken_adapter.is_available():
        print("ERROR: the Kraken Python package is not installed, so no recognition can run. "
              "Install it (pip install \"kraken>=4.3\") — see docs/OCR.md.")
        return 3

    scored: list[tuple[str, str]] = []
    per_line = []
    for image_path, reference in pairs:
        result = kraken_adapter.recognize(image_path, args.checkpoint)
        hypothesis = result["text"].replace("\n", " ").strip()
        scored.append((reference, hypothesis))
        per_line.append({"image": image_path.name, "reference": reference,
                         "hypothesis": hypothesis})
    scores = compute_htr_scores(scored)
    record = {
        "engine": "kraken",
        # NEW-17: the dataset hash lets the backend verify the record
        # against the actual labelled dataset (sha256 over the sorted
        # relative paths + bytes of every file under the test dir;
        # the backend recomputes it identically).
        "dataset_sha256": dataset_sha256(args.test_dir),
        "script_profile": args.profile,
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "cer": scores["cer"],
        "wer": scores["wer"],
        "lines_evaluated": scores["lines"],
        "reference_chars": scores["reference_chars"],
        "reference_words": scores["reference_words"],
        "test_set": str(args.test_dir),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": kraken_adapter.detected_version(),
        "per_line": per_line,
    }
    out = args.out or (REPO / "artifacts" / "benchmarks" / f"htr-eval-{args.profile}.json")
    write_json(out, record)
    print(json.dumps({k: record[k] for k in ("script_profile", "cer", "wer", "lines_evaluated",
                                              "checkpoint_sha256")}, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
