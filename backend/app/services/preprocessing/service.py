from __future__ import annotations
import hashlib, io
from PIL import Image
from app.core.config import Settings
from app.core.errors import ValidationAppError

ALLOWED_FORMATS = {"PNG", "JPEG", "TIFF", "WEBP", "BMP"}
EXT_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "TIFF": ".tiff", "WEBP": ".webp", "BMP": ".bmp"}

def validate_and_decode(data: bytes, settings: Settings) -> dict:
    if not data:
        raise ValidationAppError("empty_upload", "Uploaded file is empty.")
    if len(data) > settings.upload_max_bytes:
        raise ValidationAppError("upload_too_large", f"File exceeds limit of {settings.upload_max_bytes} bytes.", f"got {len(data)} bytes")
    # Decompression-bomb guard must be set before opening.
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
        # verify() invalidates the image; reopen to get final metadata
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
