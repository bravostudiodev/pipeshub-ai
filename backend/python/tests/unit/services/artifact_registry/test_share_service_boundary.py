from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.connectors.api.artifacts_router import artifacts_router, get_graph_provider


@pytest.mark.parametrize("user", [
    {"userId": "owner", "orgId": "org"},
    {"token_type": "scoped", "scopes": ["record:content"], "userId": "owner", "orgId": "org"},
    {"token_type": "scoped", "scopes": ["storage:token"], "userId": "owner", "orgId": "org"},
])
def test_share_content_rejects_sessions_and_unrelated_service_scopes(user):
    app = FastAPI()

    @app.middleware("http")
    async def set_user(request: Request, call_next):
        request.state.user = user
        return await call_next(request)

    app.state.config_service = SimpleNamespace()
    app.include_router(artifacts_router)
    app.dependency_overrides[get_graph_provider] = lambda: AsyncMock()
    with patch("app.connectors.api.artifacts_router.ArtifactShareContent") as content:
        response = TestClient(app).get("/api/v1/internal/artifact-share/content")
    assert response.status_code == 403
    content.assert_not_called()


def test_share_scope_cannot_use_user_facing_authorization_endpoint():
    app = FastAPI()

    @app.middleware("http")
    async def set_user(request: Request, call_next):
        request.state.user = {"token_type": "scoped", "scopes": ["artifact-share:content"], "userId": "owner", "orgId": "org"}
        return await call_next(request)

    app.include_router(artifacts_router)
    app.dependency_overrides[get_graph_provider] = lambda: AsyncMock()
    response = TestClient(app).post('/api/v1/artifacts/artifact/share-authorization?version=1')
    assert response.status_code == 403
