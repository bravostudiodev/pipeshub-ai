import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.agents.agent_loop import image_analysis_resolver as resolver


def context() -> SimpleNamespace:
    return SimpleNamespace(
        authenticated_user_id="caller", org_id="org", conversation_id="chat",
        graph_provider=object(), blob_store=SimpleNamespace(get_record_from_storage=AsyncMock()),
    )


def image_uri() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.mark.asyncio
async def test_success_checks_membership_then_caller_acl(monkeypatch) -> None:
    ctx = context()
    membership = AsyncMock(return_value=True)
    acl = AsyncMock(return_value=True)
    monkeypatch.setattr(resolver, "caller_can_read_virtual_record", acl)
    uri = image_uri()
    ctx.blob_store.get_record_from_storage.return_value = {
        "block_containers": {"blocks": [{"type": "image", "data": {"uri": uri}}]},
    }
    assert await resolver.resolve_chat_image(ctx, "image", membership) == uri
    membership.assert_awaited_once_with("org", "caller", "chat", "image")
    assert acl.await_args.kwargs["user_id"] == "caller"
    assert acl.await_args.kwargs["is_service_account"] is False


@pytest.mark.asyncio
async def test_wrong_conversation_never_reads_or_checks_acl(monkeypatch) -> None:
    ctx = context()
    acl = AsyncMock(return_value=True)
    monkeypatch.setattr(resolver, "caller_can_read_virtual_record", acl)
    with pytest.raises(resolver.ImageAttachmentUnavailable):
        await resolver.resolve_chat_image(ctx, "other-chat-image", AsyncMock(return_value=False))
    acl.assert_not_awaited()
    ctx.blob_store.get_record_from_storage.assert_not_awaited()


@pytest.mark.asyncio
async def test_acl_denial_never_reads_storage(monkeypatch) -> None:
    ctx = context()
    monkeypatch.setattr(resolver, "caller_can_read_virtual_record", AsyncMock(return_value=False))
    with pytest.raises(resolver.ImageAttachmentUnavailable):
        await resolver.resolve_chat_image(ctx, "image", AsyncMock(return_value=True))
    ctx.blob_store.get_record_from_storage.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_or_failed_authority_fails_closed(monkeypatch) -> None:
    ctx = context()
    acl = AsyncMock(return_value=True)
    monkeypatch.setattr(resolver, "caller_can_read_virtual_record", acl)
    for membership in (None, AsyncMock(side_effect=RuntimeError("db unavailable"))):
        with pytest.raises(resolver.ImageAttachmentUnavailable):
            await resolver.resolve_chat_image(ctx, "image", membership)
    acl.assert_not_awaited()
    ctx.blob_store.get_record_from_storage.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_image_uri_is_never_returned(monkeypatch) -> None:
    ctx = context()
    monkeypatch.setattr(resolver, "caller_can_read_virtual_record", AsyncMock(return_value=True))
    ctx.blob_store.get_record_from_storage.return_value = {
        "blocks": [{"type": "image", "data": {"uri": "https://example.com/image.png"}}],
    }
    with pytest.raises(resolver.ImageAttachmentUnavailable):
        await resolver.resolve_chat_image(ctx, "image", AsyncMock(return_value=True))
