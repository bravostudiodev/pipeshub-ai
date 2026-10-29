from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connectors.api.artifacts_router import internal_share_content
from app.services.artifact_registry.models import Actor


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config_service=object())))


@pytest.mark.asyncio
async def test_internal_content_uses_only_service_token_claims():
    claims = {"orgId": "org", "userId": "owner", "artifactId": "artifact", "version": 2, "contentHash": "a" * 64}
    with patch("app.connectors.api.artifacts_router.ArtifactShareContent") as service:
        service.return_value.get_content = AsyncMock(return_value=b"pinned")
        response = await internal_share_content(request(), claims, AsyncMock())
    assert response.body == b"pinned"
    assert response.headers["cache-control"] == "no-store"
    service.return_value.get_content.assert_awaited_once_with(
        actor=Actor(org_id="org", user_id="owner"), artifact_id="artifact", version=2, pinned_hash="a" * 64
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [
    {}, {"orgId": "org", "userId": "u", "artifactId": "a", "version": True},
    {"orgId": "org", "userId": "u", "artifactId": "a", "version": 0},
])
async def test_internal_content_rejects_missing_or_invalid_claims(claims):
    with pytest.raises(HTTPException) as exc:
        await internal_share_content(request(), claims, AsyncMock())
    assert exc.value.status_code == 401
