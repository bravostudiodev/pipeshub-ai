from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.agent_loop import image_membership_client as client


@pytest.mark.asyncio
async def test_checks_node_with_scoped_caller_identity(monkeypatch) -> None:
    config = SimpleNamespace(get_config=AsyncMock(return_value={"nodejs": {"endpoint": "http://node:3000"}}))
    mint = AsyncMock(return_value="service-token")
    monkeypatch.setattr(client, "generate_jwt", mint)
    post = AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: {"allowed": True}))
    session = SimpleNamespace(post=post)
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: manager)
    assert await client.chat_image_is_member(config, "org", "user", "chat", "image")
    assert mint.await_args.args[1] == {
        "orgId": "org", "userId": "user", "scopes": ["conversation:image-membership"],
    }
    assert post.await_args.kwargs["json"] == {"conversationId": "chat", "virtualRecordId": "image"}


@pytest.mark.asyncio
async def test_membership_failure_denies(monkeypatch) -> None:
    config = SimpleNamespace(get_config=AsyncMock(side_effect=RuntimeError("unavailable")))
    assert not await client.chat_image_is_member(config, "org", "user", "chat", "image")
