from __future__ import annotations
import io, tempfile
from pathlib import Path
from app.core.config import Settings
from app.core.errors import AppError, UnavailableError
from app.services.preprocessing.service import preprocess_image
from . import tesseract_adapter, kraken_adapter

# Both initial profiles are written in Hebrew script, so both use the
# Hebrew traineddata. The profile is recorded on every result; Syriac
# traineddata is never substituted for Hebrew-script Aramaic.
PROFILE_OCR_LANG = {"biblical_hebrew": "heb", "biblical_aramaic": "heb"}

def ocr_status(settings: Settings) -> dict:
    tess = tesseract_adapter.is_available(settings.tesseract_cmd)
    data_ok = tesseract_adapter.traineddata_available(settings.tesseract_lang, settings.tessdata_prefix)
    return {
        "tesseract": {"available": tess, "path": tesseract_adapter.tesseract_path(settings.tesseract_cmd),
                      "traineddata": {"lang": settings.tesseract_lang, "available": data_ok,
                                      "prefix": str(settings.tessdata_prefix) if settings.tessdata_prefix else None},
                      "reason": None if tess else "tesseract binary not found (AHAIET_TESSERACT_CMD / PATH)"},
        "kraken": {"available": kraken_adapter.is_available(),
                   "reason": None if kraken_adapter.is_available() else "kraken Python package not installed / no historical-script model provisioned"},
        "status": "available" if tess else "unavailable",
    }

def run_ocr(image_path: Path, settings: Settings, language_profile: str | None = None,
            preprocessing_profile: str = "conservative", psm: int | None = None) -> dict:
    """Full OCR path: stored original -> preprocessing (derived copy) ->
    Tesseract TSV -> text + uncertainty spans. The original file on disk
    is never modified."""
    st = ocr_status(settings)
    if st["status"] != "available":
        raise UnavailableError("ocr_unavailable",
            "No OCR engine is provisioned on this machine, so no text was extracted. Nothing was fabricated.",
            "Install Tesseract with Hebrew traineddata (heb) — see docs/OCR.md and scripts/provision-ocr.ps1 — then retry.")
    profile = language_profile or "biblical_hebrew"
    lang = PROFILE_OCR_LANG.get(profile, settings.tesseract_lang)
    original_bytes = image_path.read_bytes()
    derived, report = preprocess_image(original_bytes, preprocessing_profile, settings)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(derived); tmp_path = Path(tmp.name)
    try:
        result = tesseract_adapter.run_tesseract_tsv(
            tmp_path, settings.tesseract_cmd, lang,
            psm if psm is not None else settings.ocr_psm, settings.tessdata_prefix)
    finally:
        tmp_path.unlink(missing_ok=True)
    text = result["text"]
    if not text.strip():
        raise AppError(422, "empty_transcription",
                       "OCR ran but recognised no text in this image.",
                       "Try the 'enhanced' preprocessing profile, a higher-resolution image, or check the image actually contains Hebrew-script text.")
    threshold = settings.ocr_confidence_threshold
    uncertain = [
        {"text": w["text"], "conf": w["conf"], "line": w["line"],
         "left": w["left"], "top": w["top"], "width": w["width"], "height": w["height"]}
        for w in result["words"] if 0 <= w["conf"] < threshold
    ]
    return {
        "original_ocr_text": text,
        "uncertain_spans": uncertain,
        "mean_confidence": result["mean_confidence"],
        "word_count": len(result["words"]),
        "ocr_engine": "tesseract",
        "ocr_lang": lang,
        "ocr_profile": profile,
        "ocr_profile_note": ("Biblical Aramaic in Hebrew script is recognised with the Hebrew "
                             "traineddata (heb); Syriac traineddata is not used for Hebrew-script text."
                             if profile == "biblical_aramaic" else
                             "Hebrew traineddata (heb) used for the Biblical Hebrew profile."),
        "psm": result["psm"],
        "preprocessing": report,
    }
