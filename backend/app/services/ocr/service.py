from __future__ import annotations
from pathlib import Path
from app.core.config import Settings
from app.core.errors import UnavailableError
from . import tesseract_adapter, kraken_adapter

def ocr_status(settings: Settings) -> dict:
    tess = tesseract_adapter.is_available(settings.tesseract_cmd)
    return {
        "tesseract": {"available": tess, "path": tesseract_adapter.tesseract_path(settings.tesseract_cmd),
                      "reason": None if tess else "tesseract binary not found on PATH"},
        "kraken": {"available": kraken_adapter.is_available(),
                   "reason": None if kraken_adapter.is_available() else "kraken Python package not installed / no historical-script model provisioned"},
        "status": "available" if tess else "unavailable",
    }
def run_ocr(image_path: Path, settings: Settings, language_profile: str | None = None) -> str:
    st = ocr_status(settings)
    if st["status"] != "available":
        raise UnavailableError("ocr_unavailable",
            "No OCR engine is provisioned on this machine, so no text was extracted. Nothing was fabricated.",
            "Install Tesseract with Hebrew traineddata (heb) — see docs/OCR.md and scripts/provision-models.ps1 — then retry.")
    return tesseract_adapter.run_tesseract(image_path, settings.tesseract_cmd, settings.tesseract_lang)
