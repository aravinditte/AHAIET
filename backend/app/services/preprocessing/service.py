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
import hashlib, io, math
import numpy as np
from PIL import Image, ImageOps
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
    Image.MAX_IMAGE_PIXELS = settings.upload_max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            if fmt not in ALLOWED_FORMATS:
                raise ValidationAppError("unsupported_format", f"Unsupported image format: {fmt}", "Allowed: PNG, JPEG, TIFF, WEBP, BMP")
            width, height = probe.size
            if width * height > settings.upload_max_pixels:
                raise ValidationAppError("image_too_many_pixels", f"Image has {width*height} pixels, limit is {settings.upload_max_pixels}.")
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
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

def _projection_score(binary: np.ndarray, angle: float) -> float:
    """Variance of the horizontal projection after rotating by `angle`."""
    img = Image.fromarray(binary)
    rot = img.rotate(angle, resample=Image.BILINEAR, fillcolor=0)
    arr = np.asarray(rot, dtype=np.float64)
    proj = arr.sum(axis=1)
    return float(proj.var())

def _deskew(gray_img: Image.Image, max_angle: float = 3.0, step: float = 0.5) -> tuple[Image.Image, float]:
    """Bounded projection-profile deskew on a downscaled copy; the chosen
    angle is then applied to the full-resolution image."""
    small = gray_img.copy()
    small.thumbnail((800, 800))
    binary = (np.asarray(small) < 128).astype(np.uint8) * 255
    if binary.sum() == 0:
        return gray_img, 0.0
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
    """3x3 median via NumPy padding (conservative noise reduction)."""
    p = np.pad(gray, 1, mode="edge")
    windows = np.stack([p[i:i + gray.shape[0], j:j + gray.shape[1]]
                          for i in range(3) for j in range(3)])
    return np.median(windows, axis=0).astype(np.uint8)

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
        img = ImageOps.exif_transpose(src)
        steps.append({"step": "exif_orientation", "applied": img.size != original_size or True,
                      "note": "EXIF orientation applied via ImageOps.exif_transpose"})
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
            arr2 = np.asarray(img)
            med = _median3(arr2)
            diff_ratio = float((np.abs(arr2.astype(int) - med.astype(int)) > 24).mean())
            if diff_ratio < 0.02:
                img = Image.fromarray(med)
                steps.append({"step": "median_noise_reduction", "applied": True,
                              "note": f"fine-detail ratio {diff_ratio:.4f} below 0.02 threshold"})
            else:
                steps.append({"step": "median_noise_reduction", "applied": False,
                              "note": f"skipped: fine-detail ratio {diff_ratio:.4f} >= 0.02 (small marks preserved)"})
        else:
            steps.append({"step": "deskew", "applied": False, "note": "not in conservative profile"})
            steps.append({"step": "median_noise_reduction", "applied": False,
                          "note": "not in conservative profile (small marks preserved)"})
        # Upscale small images toward the OCR target DPI scale.
        w, h = img.size
        scale = 1.0
        if max(w, h) < 2000:
            scale = min(3.0, 2000 / max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        steps.append({"step": "upscale_to_target_dpi", "applied": scale != 1.0,
                      "scale": round(scale, 3), "target_dpi": TARGET_DPI,
                      "size_after": list(img.size)})
        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(TARGET_DPI, TARGET_DPI))
        derived = buf.getvalue()
    report = {"profile": profile, "original_size": list(original_size),
              "derived_size": list(img.size), "steps": steps}
    return derived, report
