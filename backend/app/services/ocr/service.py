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
import tempfile
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
    tess = tesseract_adapter.is_available(settings.tesseract_cmd)
    data_ok = tesseract_adapter.traineddata_available(settings.tesseract_lang, settings.tessdata_prefix)
    tesseract_ready = bool(tess and data_ok)
    kraken = kraken_adapter.status(settings)
    matrix = script_profiles.support_matrix(settings, tesseract_ready)
    any_supported = any(row["status"] == "supported" for row in matrix)
    return {
        "tesseract": {"available": tess, "path": tesseract_adapter.tesseract_path(settings.tesseract_cmd),
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


def _tesseract_ready(settings: Settings) -> bool:
    return bool(tesseract_adapter.is_available(settings.tesseract_cmd)
                and tesseract_adapter.traineddata_available(settings.tesseract_lang,
                                                            settings.tessdata_prefix))


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
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(derived); tmp_path = Path(tmp.name)
    try:
        with timer.stage("ocr"):
            result = tesseract_adapter.run_tesseract_tsv(
                tmp_path, settings.tesseract_cmd, lang,
                psm if psm is not None else settings.ocr_psm, settings.tessdata_prefix)
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
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
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


def run_ocr(image_path: Path, settings: Settings, language_profile: str | None = None,
            preprocessing_profile: str = "conservative", psm: int | None = None,
            engine: str = "auto", script_profile: str = "hebrew_square") -> dict:
    """Full OCR path: stored original -> preprocessing (derived copy) ->
    engine -> text + uncertainty spans. The original file on disk is
    never modified."""
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
    result["uncertain_spans"] = [
        {"text": w["text"], "conf": w["conf"], "line": w["line"],
         "left": w["left"], "top": w["top"], "width": w["width"], "height": w["height"]}
        for w in words if 0 <= w["conf"] < threshold
    ]
    result["word_count"] = len(words)
    result["script_profile"] = script_profile
    result["stage_timings_ms"] = timer.as_dict()
    return result
