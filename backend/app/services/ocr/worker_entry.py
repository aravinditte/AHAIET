"""OCR worker entry point (NEW-16).

Run as a subprocess by the background job runner:

    python -m app.services.ocr.worker_entry <request.json> <result.json>

The job path never runs OCR in the worker thread itself: OCR/HTR can
hang (a stuck Tesseract, a pathological Kraken checkpoint), and an
in-process call cannot be interrupted. As a subprocess, the worker is
bounded by the job's remaining deadline — on expiry or cancellation
the runner terminates it and the job still reaches a terminal state.

The request JSON carries the upload path, the OCR parameters, and the
settings overrides that differ from the environment (paths as
strings), so a job submitted against non-default settings (e.g. a
test database) is executed against exactly those settings. The
result JSON is {"ok": true, "result": {...}} or
{"ok": false, "error": {code, message, detail, status}}.
"""
from __future__ import annotations
import json
import sys
from dataclasses import replace
from pathlib import Path

_PATH_FIELDS = {"storage_dir", "db_path", "models_manifest",
                "datasets_manifest", "corpus_dir", "tessdata_prefix"}


def _settings_from_overrides(overrides: dict):
    from app.core.config import Settings
    base = Settings.from_env()
    clean = {}
    for key, value in (overrides or {}).items():
        if key in _PATH_FIELDS:
            clean[key] = Path(value) if value else None
        else:
            clean[key] = value
    return replace(base, **clean) if clean else base


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    request_path, result_path = Path(argv[0]), Path(argv[1])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    settings = _settings_from_overrides(request.get("settings") or {})
    from app.core.errors import AppError
    from app.services.ocr.service import run_ocr
    try:
        result = run_ocr(Path(request["upload_path"]), settings,
                         request.get("language_profile"),
                         request.get("preprocessing_profile") or "conservative",
                         request.get("psm"),
                         engine=request.get("engine") or "auto",
                         script_profile=request.get("script_profile") or "hebrew_square")
        payload = {"ok": True, "result": result}
    except AppError as e:
        payload = {"ok": False, "error": {"code": e.code, "message": e.message,
                                          "detail": e.detail, "status": e.status_code}}
    except Exception as e:  # reported, never hidden
        payload = {"ok": False, "error": {"code": "ocr_worker_error",
                                          "message": f"{type(e).__name__}: {e}",
                                          "detail": None, "status": 500}}
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
