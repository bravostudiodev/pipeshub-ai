from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connectors.api.artifacts_router import authorize_artifact_share
from app.services.artifact_registry.access import ArtifactNotFoundError
from app.services.artifact_registry.models import Actor


@pytest.mark.asyncio
async def test_route_uses_request_identity_not_client_identity():
    request = SimpleNamespace(state=SimpleNamespace(user={"userId": "owner", "orgId": "org"}))
    graph = object()
    with patch("app.connectors.api.artifacts_router.ArtifactShareAuthorization") as policy, patch("app.connectors.api.artifacts_router.ArtifactGalleryService") as gallery:
        policy.return_value.authorize = AsyncMock(return_value="a" * 64)
        gallery.return_value.get = AsyncMock(return_value=SimpleNamespace(name="file.html", mime_type="text/html"))
        result = await authorize_artifact_share(request, "artifact", 2, graph)
    assert result == {"authorized": True, "contentHash": "a" * 64, "name": "file.html", "mimeType": "text/html"}
    policy.assert_called_once_with(graph)
    policy.return_value.authorize.assert_awaited_once_with(
        Actor(user_id="owner", org_id="org"), "artifact", 2
    )


@pytest.mark.asyncio
async def test_route_hides_denial_and_does_not_grant_permission():
    request = SimpleNamespace(state=SimpleNamespace(user={"userId": "reader", "orgId": "org"}))
    with patch("app.connectors.api.artifacts_router.ArtifactShareAuthorization") as policy:
        policy.return_value.authorize = AsyncMock(side_effect=ArtifactNotFoundError("private details"))
        with pytest.raises(HTTPException) as error:
            await authorize_artifact_share(request, "artifact", 1, object())
    assert error.value.status_code == 404
    assert error.value.detail == "Artifact or version not found"


@pytest.mark.asyncio
async def test_route_rejects_missing_identity():
    request = SimpleNamespace(state=SimpleNamespace(user={}))
    with pytest.raises(HTTPException) as error:
        await authorize_artifact_share(request, "artifact", 1, object())
    assert error.value.status_code == 401
