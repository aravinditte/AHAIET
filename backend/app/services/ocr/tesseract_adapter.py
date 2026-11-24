"""Tesseract adapter: runs the real local binary.

Hebrew-script profiles (Biblical Hebrew AND Biblical Aramaic in Hebrew
script) both use the `heb` traineddata. Syriac traineddata is never used
for Hebrew-script Aramaic. Word confidences come from Tesseract's own TSV
output; nothing is estimated or invented here.
"""
from __future__ import annotations
import csv, io, os, shutil, subprocess
from pathlib import Path
from app.core.errors import AppError, UnavailableError

def tesseract_path(cmd: str = "tesseract") -> str | None:
    if os.path.sep in cmd or (os.path.altsep and os.path.altsep in cmd):
        return cmd if Path(cmd).exists() else None
    return shutil.which(cmd)

def is_available(cmd: str = "tesseract") -> bool:
    return tesseract_path(cmd) is not None

def _env(tessdata_prefix: Path | None) -> dict:
    env = dict(os.environ)
    if tessdata_prefix is not None:
        env["TESSDATA_PREFIX"] = str(tessdata_prefix)
    return env

def traineddata_available(lang: str, tessdata_prefix: Path | None) -> bool:
    if tessdata_prefix is not None:
        return (tessdata_prefix / f"{lang}.traineddata").exists()
    # Without an explicit prefix we cannot know Tesseract's data dir in
    # advance; the run itself will fail honestly if the data is missing.
    return True

def parse_tsv(tsv_text: str) -> dict:
    """Parse Tesseract TSV output (the format produced by the `tsv`
    config) into words with confidences, text reconstructed in TSV
    reading order (block/par/line/word), and the mean word confidence.

    This is a pure parser: it runs no OCR. Tests feed it a recorded
    TSV fixture string — a parser fixture, not OCR output — and the
    live path below feeds it the real binary's stdout."""
    words: list[dict] = []
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf", "-1"))
        except ValueError:
            conf = -1.0
        words.append({
            "text": text, "conf": conf,
            "block": int(row.get("block_num") or 0), "par": int(row.get("par_num") or 0),
            "line": int(row.get("line_num") or 0), "word": int(row.get("word_num") or 0),
            "left": int(row.get("left") or 0), "top": int(row.get("top") or 0),
            "width": int(row.get("width") or 0), "height": int(row.get("height") or 0),
        })
    # Reading order: TSV rows are already emitted in reading order; group
    # words into lines to rebuild the text faithfully.
    lines: list[str] = []
    current_key: tuple | None = None
    current: list[str] = []
    for w in words:
        key = (w["block"], w["par"], w["line"])
        if current_key is not None and key != current_key:
            lines.append(" ".join(current)); current = []
        current_key = key
        current.append(w["text"])
    if current:
        lines.append(" ".join(current))
    text = "\n".join(lines)
    confs = [w["conf"] for w in words if w["conf"] >= 0]
    mean_conf = round(sum(confs) / len(confs), 2) if confs else None
    return {"text": text, "words": words, "mean_confidence": mean_conf}


def run_tesseract_tsv(image_path: Path, cmd: str = "tesseract", lang: str = "heb",
                      psm: int = 6, tessdata_prefix: Path | None = None) -> dict:
    """Run Tesseract with TSV output. Returns words with real confidences,
    text reconstructed in TSV reading order (block/par/line/word), the
    mean word confidence, and the engine's raw stdout text."""
    exe = tesseract_path(cmd)
    if not exe:
        raise UnavailableError("ocr_engine_unavailable",
            "Tesseract OCR binary is not installed, so OCR cannot run.",
            "Install Tesseract (https://github.com/tesseract-ocr/tesseract) and the Hebrew traineddata file (heb), then restart the backend. See docs/OCR.md and scripts/provision-ocr.ps1.")
    proc = subprocess.run([exe, str(image_path), "stdout", "-l", lang, "--psm", str(psm), "tsv"],
                          capture_output=True, text=True, timeout=180, env=_env(tessdata_prefix))
    if proc.returncode != 0:
        raise UnavailableError("ocr_failed", "Tesseract OCR failed.", (proc.stderr or "")[:500])
    parsed = parse_tsv(proc.stdout)
    return {**parsed, "engine": "tesseract", "lang": lang, "psm": psm}

def run_tesseract(image_path: Path, cmd: str = "tesseract", lang: str = "heb",
                  psm: int = 6, tessdata_prefix: Path | None = None) -> str:
    """Backwards-compatible plain-text entry point."""
    return run_tesseract_tsv(image_path, cmd, lang, psm, tessdata_prefix)["text"]
