from __future__ import annotations
import shutil, subprocess
from pathlib import Path
from app.core.errors import UnavailableError

def tesseract_path(cmd: str = "tesseract") -> str | None:
    return shutil.which(cmd)
def is_available(cmd: str = "tesseract") -> bool:
    return tesseract_path(cmd) is not None
def run_tesseract(image_path: Path, cmd: str = "tesseract", lang: str = "heb") -> str:
    exe = tesseract_path(cmd)
    if not exe:
        raise UnavailableError("ocr_engine_unavailable",
            "Tesseract OCR binary is not installed, so OCR cannot run.",
            "Install Tesseract (https://github.com/tesseract-ocr/tesseract) and a Hebrew traineddata file (heb), then restart the backend. See docs/OCR.md.")
    proc = subprocess.run([exe, str(image_path), "stdout", "-l", lang, "--psm", "6"],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise UnavailableError("ocr_failed", "Tesseract OCR failed.", (proc.stderr or "")[:500])
    return proc.stdout
