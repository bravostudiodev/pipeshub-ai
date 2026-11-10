import base64
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.agents.agent_loop import image_analysis_provider as provider
from app.agents.agent_loop.image_analysis_input import InvalidAnalysisImage


def png_uri(size: tuple[int, int] = (2, 2)) -> str:
    data = io.BytesIO()
    Image.new("RGB", size, "red").save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()


@pytest.mark.asyncio
async def test_selects_dedicated_qwen_config_not_default_or_indexing(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_ANALYSIS_MODEL_NAME", raising=False)
    vision = {"provider": "litellmProxy", "isMultimodal": True, "configuration": {
        "model": "qwen3-vl-32b-instruct", "endpoint": "http://gateway:4000", "apiKey": "secret",
    }}
    text = {"provider": "litellmProxy", "isDefault": True, "configuration": {"model": "deepseek"}}
    settings = {"llm": [text, vision], "modelRoles": {"indexing": {"modelKey": "text"}}}
    config_service = SimpleNamespace(get_config=AsyncMock(return_value=settings))
    sentinel = object()
    def create(provider_name, config, *_args) -> object:
        assert provider_name == "litellmProxy" and config is vision
        return sentinel
    monkeypatch.setattr(provider, "get_generator_model", create)
    model, config = await provider._get_image_analysis_model(config_service)
    assert model is sentinel and config is vision


@pytest.mark.asyncio
async def test_admin_can_select_different_configured_vision_model(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_ANALYSIS_MODEL_NAME", "different-vision")
    config = {"provider": "litellmProxy", "isMultimodal": True, "configuration": {"model": "different-vision"}}
    service = SimpleNamespace(get_config=AsyncMock(return_value={"llm": [config]}))
    monkeypatch.setattr(provider, "get_generator_model", lambda *_args: object())
    _, selected = await provider._get_image_analysis_model(service)
    assert selected is config


@pytest.mark.asyncio
@pytest.mark.parametrize("configs", [[], [
    {"provider": "litellmProxy", "configuration": {"model": "qwen3-vl-32b-instruct"}},
], [
    {"provider": "litellmProxy", "isMultimodal": True, "configuration": {"model": "qwen3-vl-32b-instruct"}},
    {"provider": "litellmProxy", "isMultimodal": True, "configuration": {"model": "qwen3-vl-32b-instruct"}},
]])
async def test_missing_nonvision_or_ambiguous_model_fails_closed(configs) -> None:
    config_service = SimpleNamespace(get_config=AsyncMock(return_value={"llm": configs}))
    with pytest.raises(provider.ImageAnalysisUnavailable):
        await provider._get_image_analysis_model(config_service)


@pytest.mark.asyncio
async def test_sends_image_and_minimal_instruction_to_multimodal_model(monkeypatch) -> None:
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="A red square.")))
    resolver = AsyncMock(return_value=(model, {"isMultimodal": True}))
    monkeypatch.setattr(provider, "_get_image_analysis_model", resolver)
    uri = png_uri()
    assert await provider.analyze_authorized_image(object(), uri) == "A red square."
    parts = model.ainvoke.await_args.args[0][0].content
    assert parts[1]["image_url"]["url"] == uri
    assert parts[0]["text"] == provider.DESCRIPTION_INSTRUCTION


def test_resize_preserves_aspect_ratio_and_does_not_enlarge(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_ANALYSIS_MAX_DIMENSION", raising=False)
    uri, info = provider._prepare_image(png_uri((2000, 1000)))
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
        assert image.size == (1280, 640)
    assert info["resized"] and info["original_width"] == 2000
    small = png_uri((2, 2))
    assert provider._prepare_image(small)[0] == small
    assert not provider._prepare_image(small)[1]["resized"]


def test_resize_override_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_ANALYSIS_MAX_DIMENSION", "512")
    assert provider._prepare_image(png_uri((1000, 2000)))[1]["sent_height"] == 512
    monkeypatch.setenv("IMAGE_ANALYSIS_MAX_DIMENSION", "999999")
    assert provider._max_dimension() == 1280


@pytest.mark.asyncio
async def test_logs_metadata_without_image_secrets_or_response(monkeypatch, caplog) -> None:
    response = SimpleNamespace(content="private finding", usage_metadata={"input_tokens": 42})
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
    config = {"isMultimodal": True, "configuration": {"model": "vision-model",
              "endpoint": "https://gateway.example/private-path?secret=abc", "apiKey": "private-key"}}
    monkeypatch.setattr(provider, "_get_image_analysis_model", AsyncMock(return_value=(model, config)))
    uri = png_uri((1600, 800))
    with caplog.at_level(logging.INFO, logger=provider.__name__):
        await provider.analyze_authorized_image(object(), uri)
    assert '"sent_width": 1280' in caplog.text
    assert '"gateway_host": "gateway.example"' in caplog.text
    assert '"model": "vision-model"' in caplog.text
    assert '"input_tokens": 42' in caplog.text
    for secret in (uri, "private finding", "private-key", "private-path", "secret=abc"):
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_refuses_text_only_model(monkeypatch) -> None:
    model = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(provider, "_get_image_analysis_model", AsyncMock(return_value=(model, {"isMultimodal": False})))
    with pytest.raises(provider.ImageAnalysisUnavailable):
        await provider.analyze_authorized_image(object(), png_uri())
    model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_does_not_expose_error(monkeypatch, caplog) -> None:
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("secret provider detail")))
    monkeypatch.setattr(provider, "_get_image_analysis_model", AsyncMock(return_value=(model, {"isMultimodal": True})))
    with pytest.raises(provider.ImageAnalysisUnavailable, match="vision service is unavailable") as error:
        await provider.analyze_authorized_image(object(), png_uri())
    assert "secret" not in str(error.value)
    assert "secret provider detail" not in caplog.text
    assert '"error_type": "RuntimeError"' in caplog.text


@pytest.mark.asyncio
async def test_context_error_is_classified_without_provider_text(monkeypatch, caplog) -> None:
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("maximum context length; private contents")))
    monkeypatch.setattr(provider, "_get_image_analysis_model", AsyncMock(return_value=(model, {"isMultimodal": True})))
    with pytest.raises(provider.ImageAnalysisUnavailable):
        await provider.analyze_authorized_image(object(), png_uri())
    assert '"error_category": "context_limit"' in caplog.text
    assert "private contents" not in caplog.text


@pytest.mark.asyncio
async def test_invalid_image_never_reaches_provider(monkeypatch) -> None:
    resolver = AsyncMock()
    monkeypatch.setattr(provider, "_get_image_analysis_model", resolver)
    with pytest.raises(InvalidAnalysisImage):
        await provider.analyze_authorized_image(object(), "https://example.com/image.png")
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_is_safe(monkeypatch) -> None:
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError("secret")))
    monkeypatch.setattr(provider, "_get_image_analysis_model", AsyncMock(return_value=(model, {"isMultimodal": True})))
    with pytest.raises(provider.ImageAnalysisUnavailable, match="vision service is unavailable"):
        await provider.analyze_authorized_image(object(), png_uri())
