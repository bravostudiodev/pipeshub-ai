from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.agent_loop import analyze_image_tool as module
from app.agents.agent_loop.image_analysis_provider import ImageAnalysisUnavailable
from app.agents.agent_loop.image_analysis_resolver import ImageAttachmentUnavailable


@pytest.mark.asyncio
async def test_success_returns_vision_findings(monkeypatch) -> None:
    context = SimpleNamespace(config_service=object())
    checker = AsyncMock()
    load = AsyncMock(return_value="stored-image")
    analyze = AsyncMock(return_value="A red square.")
    monkeypatch.setattr(module, "resolve_chat_image", load)
    monkeypatch.setattr(module, "analyze_authorized_image", analyze)
    result = await module.AnalyzeImageTool(context, checker).execute("image-id")
    assert result.success and result.data == "A red square."
    load.assert_awaited_once_with(context, "image-id", checker)
    analyze.assert_awaited_once_with(context.config_service, "stored-image")


@pytest.mark.asyncio
async def test_access_denial_does_not_call_vision(monkeypatch) -> None:
    context = SimpleNamespace(config_service=object())
    monkeypatch.setattr(module, "resolve_chat_image", AsyncMock(side_effect=ImageAttachmentUnavailable()))
    analyze = AsyncMock()
    monkeypatch.setattr(module, "analyze_authorized_image", analyze)
    result = await module.AnalyzeImageTool(context, AsyncMock()).execute("other-user-image")
    assert not result.success
    analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_failure_returns_safe_error(monkeypatch) -> None:
    context = SimpleNamespace(config_service=object())
    monkeypatch.setattr(module, "resolve_chat_image", AsyncMock(return_value="image"))
    monkeypatch.setattr(module, "analyze_authorized_image", AsyncMock(side_effect=ImageAnalysisUnavailable()))
    result = await module.AnalyzeImageTool(context, AsyncMock()).execute("image-id")
    assert not result.success
    assert "unavailable" in result.error
