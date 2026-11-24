"""Upload validation and OCR preprocessing.

The uploaded original is never modified: preprocessing reads the stored
bytes and returns a derived image plus a step report. Two profiles:
- conservative (default): EXIF orientation, grayscale, mild contrast,
  upscale to target DPI only. No median filtering, no deskew beyond 0 —
  small marks (niqqud, cantillation) are preserved.
- enhanced: adds projection-profile deskew (bounded search) and an
  optional 3x3 median pass that is skipped automatically when the image
  contains fine detail below the filter scale (checked via local
  variance), plus stronger adaptive contrast.
"""
from __future__ import annotations
import hashlib, io, math, warnings
import numpy as np
from PIL import Image, ImageFilter, ImageOps
from app.core.config import Settings
from app.core.errors import ValidationAppError

ALLOWED_FORMATS = {"PNG", "JPEG", "TIFF", "WEBP", "BMP"}
EXT_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "TIFF": ".tiff", "WEBP": ".webp", "BMP": ".bmp"}
PROFILES = ("conservative", "enhanced")
TARGET_DPI = 300

def validate_and_decode(data: bytes, settings: Settings) -> dict:
    if not data:
        raise ValidationAppError("empty_upload", "Uploaded file is empty.")
    if len(data) > settings.upload_max_bytes:
        raise ValidationAppError("upload_too_large", f"File exceeds limit of {settings.upload_max_bytes} bytes.", f"got {len(data)} bytes")
    # NEW-22: Image.MAX_IMAGE_PIXELS is a process-global set ONCE at
    # application startup (app.main) from configuration — it is never
    # mutated per request (concurrent requests with different
    # settings must not fight over it). The per-request ceiling is
    # enforced explicitly below from the decoded header size, before
    # any full decode.
    try:
        with warnings.catch_warnings():
            # Pillow decompression warnings are treated as errors
            # (AHAIET-024): a bomb-shaped payload must fail here, not
            # midway through preprocessing.
            warnings.simplefilter("error")
            with Image.open(io.BytesIO(data)) as probe:
                fmt = probe.format
                if fmt not in ALLOWED_FORMATS:
                    raise ValidationAppError("unsupported_format", f"Unsupported image format: {fmt}", "Allowed: PNG, JPEG, TIFF, WEBP, BMP")
                width, height = probe.size
                if width * height > settings.upload_max_pixels:
                    raise ValidationAppError("image_too_many_pixels", f"Image has {width*height} pixels, limit is {settings.upload_max_pixels}.")
                # The single-image pipeline accepts exactly one frame:
                # multipage TIFFs and animations are rejected rather
                # than silently read at frame 0 (AHAIET-024).
                frames = getattr(probe, "n_frames", 1)
                if frames and frames > 1:
                    raise ValidationAppError("multipage_image",
                        f"Image has {frames} frames/pages; the single-image pipeline accepts one.",
                        "Export the single page you want recognised and upload that.")
                probe.verify()
            with Image.open(io.BytesIO(data)) as img:
                # Fully decode the second open as well (AHAIET-024):
                # format/size alone do not prove the payload decodes.
                img.load()
                width, height = img.size; fmt = img.format
    except ValidationAppError:
        raise
    except Image.DecompressionBombError as e:
        raise ValidationAppError("image_too_many_pixels", "Image exceeds pixel limit (possible decompression bomb).", str(e))
    except Exception as e:
        raise ValidationAppError("invalid_image", "File content is not a valid image (content was inspected, extension was not trusted).", str(e))
    sha = hashlib.sha256(data).hexdigest()
    return {"format": fmt, "width": width, "height": height, "size_bytes": len(data), "sha256": sha, "extension": EXT_BY_FORMAT[fmt]}

def _clahe_like(gray: np.ndarray, clip: float = 2.0, tiles: int = 8) -> np.ndarray:
    """Tile-wise histogram equalization with clipping (NumPy CLAHE analogue)."""
    h, w = gray.shape
    out = np.empty_like(gray)
    th, tw = max(1, h // tiles), max(1, w // tiles)
    for ty in range(tiles):
        for tx in range(tiles):
            y0, y1 = ty * th, (h if ty == tiles - 1 else (ty + 1) * th)
            x0, x1 = tx * tw, (w if tx == tiles - 1 else (tx + 1) * tw)
            tile = gray[y0:y1, x0:x1]
            if tile.size == 0:
                continue
            hist, _ = np.histogram(tile, bins=256, range=(0, 256))
            limit = clip * tile.size / 256.0
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = np.cumsum(hist)
            cdf = cdf / max(cdf[-1], 1) * 255.0
            out[y0:y1, x0:x1] = cdf[tile].astype(np.uint8)
    return out

def _projection_score(darkness: np.ndarray, angle: float) -> float:
    """Variance of the horizontal projection after rotating by `angle`.

    The input is a DARKNESS map (0 = paper, 255 = ink) of the detected
    text region only, and rotation fills with 0 (paper) — consistent
    with dark-on-light pages (AHAIET-039). Black fill on an ink map
    would inject artificial ink rows/columns and skew the score; page
    borders outside the text region are excluded by the mask the
    caller builds."""
    img = Image.fromarray(darkness)
    rot = img.rotate(angle, resample=Image.BILINEAR, fillcolor=0)
    arr = np.asarray(rot, dtype=np.float64)
    proj = arr.sum(axis=1)
    return float(proj.var())

def _deskew(gray_img: Image.Image, max_angle: float = 3.0, step: float = 0.5) -> tuple[Image.Image, float]:
    """Bounded projection-profile deskew on a downscaled copy; the chosen
    angle is then applied to the full-resolution image."""
    small = gray_img.copy()
    small.thumbnail((800, 800))
    gray_arr = np.asarray(small)
    ink = gray_arr < 128
    if not ink.any():
        return gray_img, 0.0
    # Text-region mask (AHAIET-039): crop to the bounding box of ink
    # pixels (with a small margin) so page borders and marginal marks
    # outside the text block do not drive the score.
    rows = np.where(ink.any(axis=1))[0]
    cols = np.where(ink.any(axis=0))[0]
    y0, y1 = max(0, rows.min() - 4), min(ink.shape[0], rows.max() + 5)
    x0, x1 = max(0, cols.min() - 4), min(ink.shape[1], cols.max() + 5)
    binary = (ink[y0:y1, x0:x1]).astype(np.uint8) * 255
    best_angle, best_score = 0.0, _projection_score(binary, 0.0)
    n = int(max_angle / step)
    for i in range(-n, n + 1):
        a = i * step
        if a == 0.0:
            continue
        s = _projection_score(binary, a)
        if s > best_score:
            best_angle, best_score = a, s
    if best_angle == 0.0:
        return gray_img, 0.0
    return gray_img.rotate(best_angle, resample=Image.BICUBIC, fillcolor=255), best_angle

def _median3(gray: np.ndarray) -> np.ndarray:
    """3x3 median via Pillow's native MedianFilter (AHAIET-023).

    The previous implementation stacked nine full-size arrays plus a
    median buffer — at the 40 MP pixel limit that is hundreds of MB
    of intermediates. The native filter processes the image without
    materialising the stack."""
    return np.asarray(Image.fromarray(gray).filter(ImageFilter.MedianFilter(3)))

def preprocess_image(data: bytes, profile: str = "conservative",
                     settings: Settings | None = None) -> tuple[bytes, dict]:
    """Return (derived PNG bytes, step report). The input bytes are the
    stored original and are left untouched."""
    if profile not in PROFILES:
        raise ValidationAppError("unknown_preprocessing_profile",
                                 f"Unknown preprocessing profile '{profile}'.",
                                 f"Allowed: {', '.join(PROFILES)}")
    steps: list[dict] = []
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        original_size = src.size
        # Decoded + intermediate byte budget (AHAIET-023): estimate the
        # decoded frame plus the pipeline's working copies and refuse
        # before any heavy step when the budget would be exceeded.
        if settings is not None:
            decoded = original_size[0] * original_size[1] * 4
            estimated = decoded * 6
            if estimated > settings.preprocessing_max_bytes:
                raise ValidationAppError(
                    "preprocessing_budget_exceeded",
                    f"Decoded image would need about {estimated} bytes of working memory; "
                    f"the configured budget is {settings.preprocessing_max_bytes} bytes "
                    "(AHAIET_PREPROCESSING_MAX_BYTES).",
                    "Reduce the image resolution or raise the budget in configuration.")
        # Orientation (AHAIET-037): attempted always; applied only when
        # an EXIF orientation tag exists AND transposing changed the
        # image. The two facts are reported separately.
        try:
            orientation_tag = src.getexif().get(274)
        except Exception:
            orientation_tag = None
        img = ImageOps.exif_transpose(src)
        orientation_applied = orientation_tag not in (None, 1) and (
            img.size != original_size or orientation_tag in (2, 4, 5, 7))
        steps.append({"step": "exif_orientation", "attempted": True,
                      "applied": bool(orientation_applied),
                      "exif_orientation": orientation_tag,
                      "note": "EXIF orientation applied via ImageOps.exif_transpose"
                              if orientation_applied else
                              "no orientation transform was required by the EXIF data"})
        img = img.convert("L")
        steps.append({"step": "grayscale", "applied": True})
        arr = np.asarray(img)
        if profile == "enhanced":
            arr = _clahe_like(arr, clip=2.0)
            steps.append({"step": "adaptive_contrast", "applied": True, "method": "tile histogram equalization (CLAHE-like, NumPy)"})
        else:
            arr = _clahe_like(arr, clip=1.2)
            steps.append({"step": "adaptive_contrast", "applied": True, "method": "mild tile histogram equalization (CLAHE-like, NumPy)"})
        img = Image.fromarray(arr)
        deskew_angle = 0.0
        if profile == "enhanced":
            img, deskew_angle = _deskew(img)
            steps.append({"step": "deskew", "applied": deskew_angle != 0.0, "angle_degrees": deskew_angle,
                          "method": "projection-profile search, bounded ±3 degrees"})
            # Median only when fine-detail content is low: if many pixels
            # differ from their local median, the page carries small marks
            # (niqqud/cantillation) and filtering would destroy them.
            # NEW-22: the fine-detail decision is made by a cheap
            # CLASSIFIER PASS on a downscaled copy — the full-resolution
            # median is computed only when the classifier says fine
            # detail is absent, never unconditionally first.
            arr2 = np.asarray(img)
            classifier = img.copy()
            classifier.thumbnail((800, 800))
            small_arr = np.asarray(classifier)
            small_med = _median3(small_arr)
            diff_ratio = float((np.abs(small_arr.astype(int) - small_med.astype(int)) > 24).mean())
            if diff_ratio < 0.02:
                med = _median3(arr2)
                img = Image.fromarray(med)
                steps.append({"step": "median_noise_reduction", "applied": True,
                              "note": f"fine-detail ratio {diff_ratio:.4f} below 0.02 threshold "
                                      "(measured on a downscaled classifier pass; full-resolution "
                                      "median applied only after that decision)"})
            else:
                steps.append({"step": "median_noise_reduction", "applied": False,
                              "note": f"skipped: fine-detail ratio {diff_ratio:.4f} >= 0.02 "
                                      "(small marks preserved; measured on a downscaled "
                                      "classifier pass, no full-resolution median computed)"})
        else:
            steps.append({"step": "deskew", "applied": False, "note": "not in conservative profile"})
            steps.append({"step": "median_noise_reduction", "applied": False,
                          "note": "not in conservative profile (small marks preserved)"})
        # Pixel upscale for small images (AHAIET-038): this changes
        # pixel dimensions only. It does NOT recover source detail and
        # does NOT establish a scan DPI; the step is named and reported
        # accordingly (the old label "upscale_to_target_dpi" was a
        # report label only — the rename is documented in docs/OCR.md).
        w, h = img.size
        scale = 1.0
        if max(w, h) < 2000:
            scale = min(3.0, 2000 / max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        source_dpi = src.info.get("dpi")
        steps.append({"step": "pixel_upscale", "applied": scale != 1.0,
                      "scale": round(scale, 3), "scaler": "LANCZOS",
                      "size_before": [w, h], "size_after": list(img.size),
                      "source_dpi": list(source_dpi) if source_dpi else None,
                      "note": "pixel dimensions increased for the OCR engine; no detail "
                              "is recovered and no scan DPI is claimed"})
        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(TARGET_DPI, TARGET_DPI))
        derived = buf.getvalue()
    report = {"profile": profile, "original_size": list(original_size),
              "derived_size": list(img.size), "steps": steps}
    return derived, report
