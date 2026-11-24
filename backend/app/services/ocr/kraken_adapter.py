"""Kraken OCR/HTR adapter: real local checkpoint loading and recognition.

Kraken is an optional dependency (training extra, Linux/WSL2-first).
This adapter:

- detects the Python package (importlib) and the `ketos` CLI, and
  reports the detected package version;
- resolves checkpoints from the models manifest (kind=ocr,
  engine=kraken, .mlmodel files that live outside source control);
- recognises a page image through Kraken's documented pipeline —
  baseline segmentation (blla) followed by the `rpred` recognition
  iterator over a loaded checkpoint — behind version-tolerant imports:
  Kraken's module layout moved between releases, so several documented
  import locations are tried, and if none of them exposes the expected
  callables the adapter reports `adapter_incompatible` with the
  detected version instead of crashing or guessing.

Per-line text and character confidences are taken from the recognition
records the library actually returns; nothing is estimated. Reading
order is the segmentation order.
"""
from __future__ import annotations
import importlib
import importlib.metadata
import shutil
from pathlib import Path

from app.core.errors import AppError, UnavailableError


class KrakenIncompatible(AppError):
    """The installed Kraken's API surface differs from every documented
    layout this adapter knows — reported, never worked around silently."""

    def __init__(self, version: str | None, detail: str):
        super().__init__(503, "kraken_adapter_incompatible",
                         "The installed Kraken version's API is not compatible with this adapter, "
                         "so Kraken recognition was not attempted.",
                         f"Detected kraken version: {version or 'unknown'}. {detail}")


def detected_version() -> str | None:
    try:
        return importlib.metadata.version("kraken")
    except Exception:
        return None


def is_available() -> bool:
    try:
        import kraken  # noqa: F401
        return True
    except Exception:
        return False


def ketos_path(cmd: str = "ketos") -> str | None:
    return shutil.which(cmd)


def status(settings) -> dict:
    pkg = is_available()
    cli = ketos_path(getattr(settings, "kraken_cmd", "ketos"))
    from . import script_profiles
    checkpoints = script_profiles.kraken_checkpoints(settings)
    available = pkg or cli is not None
    return {
        "available": available,
        "package_installed": pkg,
        "version": detected_version(),
        "ketos_cli": cli,
        "checkpoints": checkpoints,
        "reason": None if available else
        "Kraken is not installed (Python package and ketos CLI both absent) and no historical-script "
        "checkpoint is provisioned. See docs/OCR.md and scripts/provision-kraken.ps1.",
    }


def _load_pipeline():
    """Resolve (segment_fn, load_any, rpred) across Kraken's documented
    module layouts. Returns (callables, version) or raises
    KrakenIncompatible naming what was found."""
    version = detected_version()
    segment_fn = None
    for module_name, attr in (("kraken", "blla"), ("kraken.lib.segmentation", None)):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        candidate = getattr(module, attr, None) if attr else module
        seg = getattr(candidate, "segment", None) or getattr(candidate, "blla_segment", None)
        if callable(seg):
            segment_fn = seg
            break
    load_any = None
    rpred = None
    for module_name in ("kraken.lib.models", "kraken.models"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        if callable(getattr(module, "load_any", None)):
            load_any = module.load_any
            break
    for module_name in ("kraken.lib.rpred", "kraken.rpred"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        if callable(getattr(module, "rpred", None)):
            rpred = module.rpred
            break
    if segment_fn is None or load_any is None or rpred is None:
        missing = [name for name, fn in (("segmentation (blla)", segment_fn),
                                         ("model loading (load_any)", load_any),
                                         ("recognition iterator (rpred)", rpred)) if fn is None]
        raise KrakenIncompatible(version, "Missing documented callables: " + ", ".join(missing) + ".")
    return segment_fn, load_any, rpred, version


def recognize(image_path: Path, checkpoint_path: Path) -> dict:
    """Run Kraken page recognition with a local checkpoint.

    Returns {text, words, mean_confidence, lines, engine_version} in the
    same shape family as the Tesseract adapter result: words carry the
    per-character confidences Kraken reports (scaled to 0–100), lines
    keep segmentation order."""
    if not is_available():
        raise UnavailableError("kraken_unavailable",
                               "The Kraken Python package is not installed, so Kraken recognition cannot run.",
                               "Install the training extra (pip install kraken) — Linux/WSL2-first; "
                               "see docs/OCR.md and scripts/provision-kraken.ps1.")
    if not Path(checkpoint_path).is_file():
        raise UnavailableError("kraken_checkpoint_missing",
                               "The Kraken checkpoint file is not present on disk.",
                               f"Expected checkpoint at {checkpoint_path}.")
    segment_fn, load_any, rpred, version = _load_pipeline()
    from PIL import Image
    image = Image.open(image_path)
    if image.mode not in ("1", "L", "RGB"):
        image = image.convert("RGB")
    try:
        segmentation = segment_fn(image)
        model = load_any(str(checkpoint_path))
        records = list(rpred(model, image, segmentation))
    except KrakenIncompatible:
        raise
    except Exception as e:  # a real engine failure is reported, not hidden
        raise UnavailableError("kraken_failed", "Kraken recognition failed.", str(e)[:500]) from e
    lines: list[dict] = []
    words: list[dict] = []
    all_conf: list[float] = []
    for line_no, record in enumerate(records):
        text = (getattr(record, "prediction", "") or "").strip()
        confidences = [float(c) * 100.0 for c in (getattr(record, "confidences", None) or [])]
        all_conf.extend(confidences)
        lines.append({"line": line_no, "text": text,
                      "mean_confidence": round(sum(confidences) / len(confidences), 2)
                      if confidences else None})
        # Word-level view: split the line prediction; per-word confidence
        # is the mean of that word's character confidences when Kraken
        # provides character-aligned confidences of matching length.
        chars = list(text.replace(" ", ""))
        offset = 0
        for word in text.split():
            n = len(word)
            word_conf = confidences[offset:offset + n] if len(confidences) >= len(chars) else []
            offset += n
            words.append({"text": word,
                          "conf": round(sum(word_conf) / len(word_conf), 2) if word_conf else -1.0,
                          "line": line_no, "left": 0, "top": 0, "width": 0, "height": 0})
    full_text = "\n".join(line["text"] for line in lines if line["text"])
    return {"text": full_text, "words": words,
            "mean_confidence": round(sum(all_conf) / len(all_conf), 2) if all_conf else None,
            "lines": lines, "engine_version": version}
