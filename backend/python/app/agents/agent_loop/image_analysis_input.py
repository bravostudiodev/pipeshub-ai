"""Validation for image analysis inputs loaded from trusted storage.

This module does not authorize or load references. Callers must establish chat
membership and the authenticated user's access before passing any stored data
here. Never pass model-provided URLs or bytes to this function.
"""
from __future__ import annotations

import base64
import binascii
import io
import warnings

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


class InvalidAnalysisImage(ValueError):
    """Image data cannot safely be sent to the vision provider."""


def validate_stored_image_data_uri(uri: str) -> str:
    """Validate a single stored data URI and return its canonical representation.

    Reject URLs, MIME/format mismatches, animated images, oversized data and
    decompression bombs. Verify and fully decode before sending to the model.
    """
    if not isinstance(uri, str) or len(uri) > (MAX_IMAGE_BYTES * 4 // 3 + 128):
        raise InvalidAnalysisImage("Image is invalid or too large")
    header, separator, payload = uri.partition(",")
    if not separator or not header.startswith("data:") or not header.endswith(";base64"):
        raise InvalidAnalysisImage("Image must be stored as base64 image data")
    mime = header[5:-7].lower()
    expected = _FORMATS.get(mime)
    if expected is None:
        raise InvalidAnalysisImage("Unsupported image format")
    try:
        raw = base64.b64decode(payload, validate=True)
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise InvalidAnalysisImage("Image is empty or too large")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != expected or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidAnalysisImage("Invalid image format or dimensions")
                if getattr(image, "n_frames", 1) != 1:
                    raise InvalidAnalysisImage("Animated images are not supported")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
    except InvalidAnalysisImage:
        raise
    except (binascii.Error, ValueError, OSError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidAnalysisImage("Image data is invalid") from exc
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
