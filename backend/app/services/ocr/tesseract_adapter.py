"""Tesseract adapter: runs the real local binary.

Hebrew-script profiles (Biblical Hebrew AND Biblical Aramaic in Hebrew
script) both use the `heb` traineddata. Syriac traineddata is never used
for Hebrew-script Aramaic. Word confidences come from Tesseract's own TSV
output; nothing is estimated or invented here.
"""
from __future__ import annotations
import csv, io, os, shutil, subprocess, threading, time
from pathlib import Path
from app.core.errors import AppError, UnavailableError, sanitize_detail


class OcrParseError(AppError):
    """Tesseract ran but its TSV output was malformed (AHAIET-022)."""

    def __init__(self, detail: str):
        super().__init__(503, "ocr_parse_error",
                         "Tesseract produced malformed TSV output, so no text was extracted.",
                         sanitize_detail(detail))

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
    """File-level check used when a prefix is configured. Readiness as
    a whole is decided by readiness() below, which asks the binary
    itself which languages it can serve (AHAIET-034)."""
    if tessdata_prefix is not None:
        return (tessdata_prefix / f"{lang}.traineddata").exists()
    return True


# --- Readiness probe (AHAIET-034) -------------------------------------
# `tesseract --list-langs` is the only honest way to know which language
# data the installed binary can actually use. The probe is bounded
# (short timeout) and cached with a TTL so /api/capabilities stays
# cheap; binary_available, language_data_available and usable are
# reported as three distinct facts.
_probe_cache: dict[tuple, tuple[float, dict]] = {}
_probe_lock = threading.Lock()


def list_languages(cmd: str = "tesseract", tessdata_prefix: Path | None = None,
                   timeout_s: float = 10.0) -> list[str] | None:
    """Languages the binary reports, or None when the probe failed."""
    exe = tesseract_path(cmd)
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "--list-langs"], capture_output=True, text=True,
                              timeout=timeout_s, env=_env(tessdata_prefix))
    except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("list of available languages"):
        lines = lines[1:]
    return lines


def readiness(cmd: str = "tesseract", lang: str = "heb",
              tessdata_prefix: Path | None = None, ttl_s: float = 30.0) -> dict:
    key = (cmd, lang, str(tessdata_prefix))
    now = time.monotonic()
    with _probe_lock:
        cached = _probe_cache.get(key)
        if cached and now - cached[0] < ttl_s:
            return dict(cached[1])
    binary = is_available(cmd)
    langs = list_languages(cmd, tessdata_prefix) if binary else None
    language_ok = (lang in langs) if langs is not None else (
        traineddata_available(lang, tessdata_prefix) if tessdata_prefix is not None else False)
    out = {"binary_available": binary,
           "language_data_available": bool(language_ok),
           "languages": langs,
           "usable": bool(binary and language_ok)}
    with _probe_lock:
        _probe_cache[key] = (now, out)
    return dict(out)

def parse_tsv(tsv_text: str) -> dict:
    """Parse Tesseract TSV output (the format produced by the `tsv`
    config) into words with confidences, text reconstructed in TSV
    reading order (block/par/line/word), and the mean word confidence.

    This is a pure parser: it runs no OCR. Tests feed it a recorded
    TSV fixture string — a parser fixture, not OCR output — and the
    live path below feeds it the real binary's stdout."""
    words: list[dict] = []
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE)

    def _int_col(row: dict, name: str) -> int:
        raw = row.get(name)
        if raw in (None, ""):
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise OcrParseError(
                f"TSV column {name} has a non-integer value {raw!r}; the OCR output "
                "cannot be trusted, so it was rejected rather than guessed at.")

    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            raise OcrParseError(
                f"TSV column conf has a non-numeric value {row.get('conf')!r}.")
        words.append({
            "text": text, "conf": conf,
            "block": _int_col(row, "block_num"), "par": _int_col(row, "par_num"),
            "line": _int_col(row, "line_num"), "word": _int_col(row, "word_num"),
            "left": _int_col(row, "left"), "top": _int_col(row, "top"),
            "width": _int_col(row, "width"), "height": _int_col(row, "height"),
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
                      psm: int = 6, tessdata_prefix: Path | None = None,
                      timeout_s: float = 120.0) -> dict:
    """Run Tesseract with TSV output. Returns words with real confidences,
    text reconstructed in TSV reading order (block/par/line/word), the
    mean word confidence, and the engine's raw stdout text.

    Failure typing (AHAIET-022): a timeout is a 504 ocr_timeout, a
    start/OS failure or non-zero exit is a 503 ocr_failed, malformed
    TSV is a 503 ocr_parse_error — never an unhandled 500, and the
    diagnostics are bounded and path-stripped."""
    exe = tesseract_path(cmd)
    if not exe:
        raise UnavailableError("ocr_engine_unavailable",
            "Tesseract OCR binary is not installed, so OCR cannot run.",
            "Install Tesseract (https://github.com/tesseract-ocr/tesseract) and the Hebrew traineddata file (heb), then restart the backend. See docs/OCR.md and scripts/provision-ocr.ps1.")
    try:
        proc = subprocess.run([exe, str(image_path), "stdout", "-l", lang, "--psm", str(psm), "tsv"],
                              capture_output=True, text=True, timeout=timeout_s,
                              env=_env(tessdata_prefix))
    except subprocess.TimeoutExpired:
        raise AppError(504, "ocr_timeout",
                       "Tesseract exceeded the configured OCR timeout, so no text was extracted.",
                       f"timeout={timeout_s}s")
    except (OSError, UnicodeDecodeError) as e:
        raise UnavailableError("ocr_failed", "Tesseract could not be run.",
                               sanitize_detail(str(e)))
    if proc.returncode != 0:
        raise UnavailableError("ocr_failed", "Tesseract OCR failed.",
                               sanitize_detail(proc.stderr or ""))
    parsed = parse_tsv(proc.stdout)
    return {**parsed, "engine": "tesseract", "lang": lang, "psm": psm}

def run_tesseract(image_path: Path, cmd: str = "tesseract", lang: str = "heb",
                  psm: int = 6, tessdata_prefix: Path | None = None,
                  timeout_s: float = 120.0) -> str:
    """Backwards-compatible plain-text entry point."""
    return run_tesseract_tsv(image_path, cmd, lang, psm, tessdata_prefix, timeout_s)["text"]
