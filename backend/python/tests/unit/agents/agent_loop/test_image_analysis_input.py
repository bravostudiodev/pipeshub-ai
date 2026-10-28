import base64
import io

import pytest
from PIL import Image

from app.agents.agent_loop.image_analysis_input import (
    MAX_IMAGE_BYTES,
    InvalidAnalysisImage,
    validate_stored_image_data_uri,
)


def image_uri(image_format="PNG", mime="image/png") -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format=image_format)
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


@pytest.mark.parametrize("image_format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_accepts_valid_images(image_format, mime) -> None:
    uri = image_uri(image_format, mime)
    assert validate_stored_image_data_uri(uri) == uri


@pytest.mark.parametrize("uri", [
    "https://example.com/image.png",
    "data:image/png;base64,not-base64!",
    "data:image/svg+xml;base64,PHN2Zz4=",
    "data:image/png;base64,",
    "data:image/png;base64," + "A" * (MAX_IMAGE_BYTES * 2),
])
def test_rejects_unsafe_or_invalid_inputs(uri) -> None:
    with pytest.raises(InvalidAnalysisImage):
        validate_stored_image_data_uri(uri)


def test_rejects_mime_spoofing() -> None:
    with pytest.raises(InvalidAnalysisImage):
        validate_stored_image_data_uri(image_uri("PNG", "image/jpeg"))


def test_rejects_animated_image() -> None:
    buffer = io.BytesIO()
    frames = [Image.new("RGB", (2, 2), color) for color in ("red", "blue")]
    frames[0].save(buffer, format="PNG", save_all=True, append_images=frames[1:])
    uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    with pytest.raises(InvalidAnalysisImage):
        validate_stored_image_data_uri(uri)
