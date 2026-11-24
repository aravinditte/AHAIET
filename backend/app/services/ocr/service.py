"""OCR routing: Tesseract baseline + Kraken historical recognition.

Engine selection rules (no silent substitutions, ever):
- script profile hebrew_square (the printed square script of both
  language profiles): engine=auto or engine=tesseract uses the
  Tesseract baseline; engine=kraken uses Kraken only when that profile
  is computed supported with a verified checkpoint — otherwise an
  explicit error, never a quiet fallback.
- A historical script profile (Paleo-Hebrew, Imperial Aramaic, Jewish
  Babylonian Aramaic hands, Syriac Estrangela): only Kraken can serve
  it, and only when the computed support matrix says supported
  (measured evaluation record + matching checkpoint hash — see
  script_profiles.py). engine=tesseract or an unsupported profile is an
  explicit error; Tesseract is never applied to a historical script.

Both Hebrew-script language profiles use the heb traineddata and the
language profile is recorded on every result; Syriac traineddata is
never substituted for Hebrew-script Aramaic.
"""
from __future__ import annotations
import contextlib
import tempfile
import threading
from pathlib import Path
from app.core.config import Settings
from app.core.errors import AppError, UnavailableError, ValidationAppError
from app.core.timing import StageTimer
from app.services.preprocessing.service import preprocess_image
from . import kraken_adapter, script_profiles, tesseract_adapter

# Both initial profiles are written in Hebrew script, so both use the
# Hebrew traineddata. The profile is recorded on every result; Syriac
# traineddata is never substituted for Hebrew-script Aramaic.
PROFILE_OCR_LANG = {"biblical_hebrew": "heb", "biblical_aramaic": "heb"}
ENGINES = ("auto", "tesseract", "kraken")


def ocr_status(settings: Settings) -> dict:
    # AHAIET-034: readiness comes from the binary's own --list-langs
    # report (bounded, TTL-cached), reported as three distinct facts.
    probe = tesseract_adapter.readiness(settings.tesseract_cmd, settings.tesseract_lang,
                                        settings.tessdata_prefix,
                                        ttl_s=settings.tesseract_probe_ttl_s)
    tess = probe["binary_available"]
    data_ok = probe["language_data_available"]
    tesseract_ready = probe["usable"]
    kraken = kraken_adapter.status(settings)
    matrix = script_profiles.support_matrix(settings, tesseract_ready)
    any_supported = any(row["status"] == "supported" for row in matrix)
    return {
        "tesseract": {"available": tess,
                      "binary_available": probe["binary_available"],
                      "language_data_available": probe["language_data_available"],
                      "usable": probe["usable"],
                      "languages": probe["languages"],
                      "path": tesseract_adapter.tesseract_path(settings.tesseract_cmd),
                      "traineddata": {"lang": settings.tesseract_lang, "available": data_ok,
                                      "prefix": str(settings.tessdata_prefix) if settings.tessdata_prefix else None},
                      "reason": None if tess else "tesseract binary not found (AHAIET_TESSERACT_CMD / PATH)"},
        "kraken": {"available": kraken["available"],
                   "reason": kraken["reason"],
                   "package_installed": kraken["package_installed"],
                   "version": kraken["version"],
                   "ketos_cli": kraken["ketos_cli"],
                   "checkpoints": kraken["checkpoints"]},
        "scripts": matrix,
        "status": "available" if (tesseract_ready or any_supported) else "unavailable",
    }


@contextlib.contextmanager
def _scratch_file(settings: Settings):
    """Intermediate processing file inside the configured storage area
    (settings.temp_dir), never the OS temp directory, so filesystem
    restrictions and retention cover scratch files too. The caller
    deletes the file in a finally block; this helper only creates it
    and hands over the open handle."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False,
                                     dir=settings.temp_dir) as tmp:
        yield tmp

def _tesseract_ready(settings: Settings) -> bool:
    return bool(tesseract_adapter.readiness(settings.tesseract_cmd, settings.tesseract_lang,
                                            settings.tessdata_prefix,
                                            ttl_s=settings.tesseract_probe_ttl_s)["usable"])


def _shape_result(text: str, words: list[dict], mean_confidence, engine: str,
                  profile: str, note: str, preprocessing_report, timings: dict,
                  engine_version: str | None = None) -> dict:
    return {
        "original_ocr_text": text,
        "uncertain_spans": [],  # filled by caller with the active threshold
        "_words": words,
        "mean_confidence": mean_confidence,
        "word_count": len(words),
        "ocr_engine": engine,
        "ocr_lang": "heb" if engine == "tesseract" else None,
        "ocr_profile": profile,
        "ocr_profile_note": note,
        "engine_version": engine_version,
        "preprocessing": preprocessing_report,
        "stage_timings_ms": timings,
    }


def _run_tesseract(image_path: Path, settings: Settings, language_profile: str | None,
                   preprocessing_profile: str, psm: int | None, timer: StageTimer) -> dict:
    if not _tesseract_ready(settings):
        raise UnavailableError("ocr_unavailable",
            "No OCR engine is provisioned on this machine, so no text was extracted. Nothing was fabricated.",
            "Install Tesseract with Hebrew traineddata (heb) — see docs/OCR.md and scripts/provision-ocr.ps1 — then retry.")
    profile = language_profile or "biblical_hebrew"
    lang = PROFILE_OCR_LANG.get(profile, settings.tesseract_lang)
    original_bytes = image_path.read_bytes()
    with timer.stage("preprocessing"):
        derived, report = preprocess_image(original_bytes, preprocessing_profile, settings)
    with _scratch_file(settings) as tmp:
        tmp.write(derived); tmp_path = Path(tmp.name)
    try:
        with timer.stage("ocr"):
            result = tesseract_adapter.run_tesseract_tsv(
                tmp_path, settings.tesseract_cmd, lang,
                psm if psm is not None else settings.ocr_psm, settings.tessdata_prefix,
                timeout_s=settings.ocr_timeout_s)
    finally:
        tmp_path.unlink(missing_ok=True)
    note = ("Biblical Aramaic in Hebrew script is recognised with the Hebrew "
            "traineddata (heb); Syriac traineddata is not used for Hebrew-script text."
            if profile == "biblical_aramaic" else
            "Hebrew traineddata (heb) used for the Biblical Hebrew profile.")
    out = _shape_result(result["text"], result["words"], result["mean_confidence"],
                        "tesseract", profile, note, report, {})
    out["psm"] = result["psm"]
    return out


def _run_kraken(image_path: Path, settings: Settings, language_profile: str | None,
                script_profile: str, preprocessing_profile: str, timer: StageTimer) -> dict:
    support = script_profiles.support_for(settings, script_profile, _tesseract_ready(settings))
    if support is None:
        raise ValidationAppError("unknown_script_profile",
                                 f"Unknown script profile '{script_profile}'.",
                                 "Known profiles: " + ", ".join(p["id"] for p in script_profiles.load_registry()))
    if support["status"] != "supported" or support.get("engine") != "kraken":
        raise AppError(422, "script_unsupported",
                       f"Script profile '{script_profile}' is not supported by a verified Kraken "
                       "checkpoint on this machine, so no recognition was attempted. "
                       "No other engine was substituted.",
                       support.get("reason"))
    checkpoint = Path(support["checkpoint"]["path"])
    original_bytes = image_path.read_bytes()
    with timer.stage("preprocessing"):
        derived, report = preprocess_image(original_bytes, preprocessing_profile, settings)
    with _scratch_file(settings) as tmp:
        tmp.write(derived); tmp_path = Path(tmp.name)
    try:
        with timer.stage("ocr"):
            result = kraken_adapter.recognize(tmp_path, checkpoint)
    finally:
        tmp_path.unlink(missing_ok=True)
    profile = language_profile or "biblical_hebrew"
    note = (f"Kraken historical recognition with checkpoint {support['checkpoint']['id']} "
            f"(sha256 {support['checkpoint']['sha256'][:12]}…); support for this script is "
            f"backed by a measured evaluation record (CER {support['evaluation']['cer']}).")
    out = _shape_result(result["text"], result["words"], result["mean_confidence"],
                        "kraken", profile, note, report, {},
                        engine_version=result.get("engine_version"))
    out["psm"] = None
    out["lines"] = result["lines"]
    return out


# Global OCR concurrency bound (AHAIET-033): one semaphore per
# configured limit value, shared by every OCR request in the process.
_ocr_semaphores: dict[int, threading.BoundedSemaphore] = {}
_ocr_semaphores_lock = threading.Lock()


def _ocr_semaphore(settings: Settings) -> threading.BoundedSemaphore:
    limit = max(1, settings.max_concurrent_ocr)
    with _ocr_semaphores_lock:
        sem = _ocr_semaphores.get(limit)
        if sem is None:
            sem = threading.BoundedSemaphore(limit)
            _ocr_semaphores[limit] = sem
        return sem


def run_ocr(image_path: Path, settings: Settings, language_profile: str | None = None,
            preprocessing_profile: str = "conservative", psm: int | None = None,
            engine: str = "auto", script_profile: str = "hebrew_square") -> dict:
    """Full OCR path: stored original -> preprocessing (derived copy) ->
    engine -> text + uncertainty spans. The original file on disk is
    never modified. Concurrent OCR work is bounded globally
    (AHAIET-033); when the bound is saturated the request waits for a
    slot rather than spawning unbounded engine processes."""
    with _ocr_semaphore(settings):
        return _run_ocr_bounded(image_path, settings, language_profile,
                                preprocessing_profile, psm, engine, script_profile)


def _run_ocr_bounded(image_path: Path, settings: Settings, language_profile: str | None = None,
                     preprocessing_profile: str = "conservative", psm: int | None = None,
                     engine: str = "auto", script_profile: str = "hebrew_square") -> dict:
    if engine not in ENGINES:
        raise ValidationAppError("unknown_ocr_engine",
                                 f"Unknown OCR engine '{engine}'.",
                                 "Use engine=auto, engine=tesseract, or engine=kraken.")
    timer = StageTimer()
    if script_profile != "hebrew_square":
        if engine == "tesseract":
            raise AppError(422, "script_unsupported",
                           f"Tesseract serves only the square Hebrew script profile; script profile "
                           f"'{script_profile}' requires a verified Kraken checkpoint and was not "
                           "silently rerouted.",
                           "Use engine=kraken with a supported script profile (see GET /api/scripts).")
        result = _run_kraken(image_path, settings, language_profile, script_profile,
                             preprocessing_profile, timer)
    elif engine == "kraken":
        result = _run_kraken(image_path, settings, language_profile, script_profile,
                             preprocessing_profile, timer)
    else:
        result = _run_tesseract(image_path, settings, language_profile,
                                preprocessing_profile, psm, timer)
    text = result["original_ocr_text"]
    if not text.strip():
        raise AppError(422, "empty_transcription",
                       "OCR ran but recognised no text in this image.",
                       "Try the 'enhanced' preprocessing profile, a higher-resolution image, or check the image actually contains text in the selected script.")
    threshold = settings.ocr_confidence_threshold
    words = result.pop("_words")
    # AHAIET-028/040: every span carries its token occurrence identity
    # (global word index in TSV order, block/par/line ids, and a
    # composite occurrence_id) so the UI highlights the exact
    # occurrence, never the first identical string.
    result["uncertain_spans"] = [
        {"text": w["text"], "conf": w["conf"],
         "index": i, "occurrence_id": f"w{i}",
         "block": w.get("block"), "par": w.get("par"),
         "line": w["line"], "line_id": f"b{w.get('block', 0)}p{w.get('par', 0)}l{w['line']}",
         "left": w["left"], "top": w["top"], "width": w["width"], "height": w["height"]}
        for i, w in enumerate(words) if w.get("conf") is not None and 0 <= w["conf"] < threshold
    ]
    result["word_count"] = len(words)
    result["script_profile"] = script_profile
    result["stage_timings_ms"] = timer.as_dict()
    return result
