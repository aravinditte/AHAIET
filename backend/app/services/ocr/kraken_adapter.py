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
import hashlib
import importlib
import importlib.metadata
import shutil
import threading
from collections import OrderedDict
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


def grapheme_clusters(text: str) -> list[str]:
    """Split text into grapheme-like clusters (NEW-23).

    This is a documented APPROXIMATION of UAX #29 grapheme cluster
    segmentation, tuned for Hebrew/Aramaic vocalized text: a cluster
    is a base code point plus every following combining mark
    (unicodedata categories Mn/Me, and Mc spacing marks that attach
    to the preceding base in these scripts), and ZWJ (U+200D)
    sequences are kept together. It is NOT a full UAX #29
    implementation (no extended-pictographic or regional-indicator
    rules — neither occurs in the target scripts). When the cluster
    count cannot be reconciled with Kraken's confidence count, the
    caller reports confidence_unavailable rather than misaligned
    numbers."""
    import unicodedata
    clusters: list[str] = []
    current = ""
    join_next = False
    for ch in text:
        if not current:
            current = ch
            continue
        category = unicodedata.category(ch)
        if unicodedata.combining(ch) or category in ("Mn", "Me", "Mc"):
            current += ch
        elif ch == "\u200d":
            current += ch
            join_next = True
        elif join_next:
            current += ch
            join_next = False
        else:
            clusters.append(current)
            current = ch
    if current:
        clusters.append(current)
    return clusters


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


# Loaded-model cache (AHAIET-035): Kraken checkpoints are expensive to
# load, so a loaded model is reused across requests, keyed by the
# checkpoint file's SHA-256 (a changed checkpoint is a different key),
# bounded to two entries.
_model_cache: "OrderedDict[str, object]" = OrderedDict()
_model_cache_lock = threading.Lock()
_MODEL_CACHE_MAX = 2


def _checkpoint_key(checkpoint_path: Path) -> str:
    h = hashlib.sha256()
    with Path(checkpoint_path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_model_cached(load_any, checkpoint_path: Path):
    key = _checkpoint_key(checkpoint_path)
    with _model_cache_lock:
        model = _model_cache.get(key)
        if model is not None:
            _model_cache.move_to_end(key)
            return model
    model = load_any(str(checkpoint_path))
    with _model_cache_lock:
        _model_cache[key] = model
        while len(_model_cache) > _MODEL_CACHE_MAX:
            _model_cache.popitem(last=False)
    return model


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
        model = _load_model_cached(load_any, checkpoint_path)
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
        # Confidence alignment (AHAIET-041; NEW-23): Kraken
        # confidences align to its own grapheme segmentation, so the
        # comparison uses grapheme CLUSTERS (base + combining marks,
        # ZWJ sequences), not Python code points — code-point counts
        # misalign on vocalized Hebrew/Aramaic (niqqud, cantillation,
        # ligatures). When the counts cannot be aligned reliably,
        # confidences are reported as unavailable — never fabricated
        # as zeros and never misaligned onto the wrong characters.
        graphemes = grapheme_clusters(text.replace(" ", ""))
        aligned = len(confidences) == len(graphemes)
        if aligned:
            all_conf.extend(confidences)
        # Real geometry when the segmentation provides it (AHAIET-041):
        # prefer the record's own boundary/bbox; otherwise mark the
        # geometry unavailable instead of inventing zero boxes.
        boundary = getattr(record, "boundary", None) or getattr(record, "bbox", None)
        geometry = {"boundary": boundary} if boundary else None
        lines.append({"line": line_no, "text": text,
                      "mean_confidence": round(sum(confidences) / len(confidences), 2)
                      if aligned and confidences else None,
                      "confidence_unavailable": not aligned,
                      "geometry": geometry,
                      "geometry_unavailable": geometry is None})
        # Word confidences are sliced by grapheme-cluster position,
        # and each word also records its code-point offsets within
        # the line text (NEW-21 uses the service-level assembly to
        # lift these to whole-text offsets).
        cluster_pos = 0
        char_pos = 0
        for word in text.split():
            n_clusters = len(grapheme_clusters(word))
            word_conf = confidences[cluster_pos:cluster_pos + n_clusters] if aligned else []
            cluster_pos += n_clusters
            words.append({"text": word,
                          "conf": round(sum(word_conf) / len(word_conf), 2) if word_conf else None,
                          "confidence_unavailable": not aligned,
                          "line": line_no,
                          "char_start_in_line": char_pos,
                          "char_end_in_line": char_pos + len(word),
                          "left": 0, "top": 0, "width": 0, "height": 0,
                          "geometry_unavailable": geometry is None})
            char_pos += len(word)
            # account for the single separating space consumed by split()
            while char_pos < len(text) and text[char_pos] == " ":
                char_pos += 1
    full_text = "\n".join(line["text"] for line in lines if line["text"])
    return {"text": full_text, "words": words,
            "mean_confidence": round(sum(all_conf) / len(all_conf), 2) if all_conf else None,
            "lines": lines, "engine_version": version}
