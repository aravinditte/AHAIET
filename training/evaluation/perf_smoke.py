#!/usr/bin/env python3
"""Performance smoke harness (code only — no targets are claimed).

Times the pipeline stages against the fixture image and fixture texts
when a developer runs it, and writes the measurements as JSON. It
records what this machine actually did: wall-clock time per request
plus the backend's own stage_timings_ms where the API returns them.
An unavailable stage (e.g. OCR with no Tesseract binary) is recorded
with its honest status, not skipped silently and never assigned a
made-up duration target.

Usage (backend venv, from the repo root):
    python training/evaluation/perf_smoke.py \
        [--out artifacts/benchmarks/perf-smoke.json] \
        [--fixture-image training/ocr/fixtures/genesis-1-1.png]

The fixture image is produced by training/ocr/generate_fixtures.py;
when it is absent the upload/OCR steps are recorded as blocked with
that prerequisite named, and the text-path timings still run.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

SAMPLE = REPO_ROOT / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"


def _timed(fn) -> tuple[float, object]:
    start = time.perf_counter()
    result = fn()
    return round((time.perf_counter() - start) * 1000, 2), result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Time the pipeline stages on fixture inputs (measurements only, no targets).")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "benchmarks" / "perf-smoke.json")
    ap.add_argument("--fixture-image", type=Path,
                    default=REPO_ROOT / "training" / "ocr" / "fixtures" / "genesis-1-1.png")
    args = ap.parse_args(argv)

    from fastapi.testclient import TestClient
    from app.corpus.import_morphhb import import_into_db
    from app.core.config import settings
    from app.main import create_app

    passages = [json.loads(l) for l in SAMPLE.read_text(encoding="utf-8").splitlines() if l.strip()]
    import_into_db(settings.db_path, passages)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    gen = next(p for p in passages if p["reference"] == "Genesis 1:1")

    report: dict = {"fixture_image": str(args.fixture_image), "stages_ms": {}, "notes": []}

    ms, r = _timed(lambda: client.get("/api/health"))
    report["stages_ms"]["health"] = ms
    ms, r = _timed(lambda: client.get("/api/capabilities"))
    report["stages_ms"]["capabilities"] = ms

    upload_id = None
    if args.fixture_image.exists():
        data = args.fixture_image.read_bytes()
        ms, r = _timed(lambda: client.post(
            "/api/uploads", files={"file": ("fixture.png", data, "image/png")}))
        report["stages_ms"]["upload"] = ms
        if r.status_code == 200:
            upload_id = r.json()["id"]
        else:
            report["notes"].append(f"upload returned {r.status_code}: {r.json()}")
    else:
        report["notes"].append(
            "fixture image absent — generate it with training/ocr/generate_fixtures.py; "
            "upload/OCR timings recorded as blocked")

    if upload_id:
        ms, r = _timed(lambda: client.post("/api/ocr", json={"upload_id": upload_id}))
        report["stages_ms"]["ocr_request"] = ms
        if r.status_code == 200:
            report["stage_timings_ms"] = r.json().get("stage_timings_ms", {})
        else:
            report["notes"].append(
                f"OCR unavailable on this machine ({r.status_code}: "
                f"{r.json().get('error', {}).get('code')}); no OCR timing exists")

    ms, r = _timed(lambda: client.post("/api/translate", json={
        "text": gen["source_text"], "source_language": "biblical_hebrew"}))
    report["stages_ms"]["translate_verified_reference"] = ms
    if r.status_code == 200:
        report["translate_stage_timings_ms"] = r.json().get("stage_timings_ms", {})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {args.out}. These are measurements from this run on this "
          "machine; the project states no latency targets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
