"""Refresh persistence and client binding stay server-side and user-bound."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.agents.mcp.models import OAuthTokens
from app.agents.mcp.token_refresh import (
    MCPTokenRefreshTransientError,
    resolve_client_credentials,
)
from app.api.routes import mcp_servers
from app.config.providers.in_memory_store import InMemoryKeyValueStore
from tests.unit.api.routes.test_mcp_servers import (
    TestHandleOauthCallback as CallbackCases,
)
from tests.unit.api.routes.test_mcp_servers import _mock_request
from tests.unit.api.routes.test_mcp_servers_handlers import (
    _admin_request,
    _oauth_instance,
)
from tests.unit.config.test_conditional_config import make_config


@pytest.mark.asyncio
async def test_static_client_replacement_keeps_issuing_client_without_exposing_secret() -> None:
    cfg = make_config(InMemoryKeyValueStore(MagicMock()))
    path = "/services/mcp/oauth-clients/inst-1"
    await cfg.set_config(path, {"clientId": "old-client", "clientSecret": "old-secret"})
    request = _admin_request(config_service=cfg)
    with (
        patch.object(mcp_servers, "_check_user_is_admin", AsyncMock(return_value=True)),
        patch.object(mcp_servers, "_get_org_instance", AsyncMock(return_value=_oauth_instance())),
    ):
        await mcp_servers.update_oauth_config(
            request, "inst-1", mcp_servers.OAuthClientConfigRequest(clientId="new-client", clientSecret="new-secret"),
        )
        assert await resolve_client_credentials("inst-1", "user-1", cfg, issued_by="old-client") == ("old-client", "old-secret")
        public_config = await mcp_servers.get_oauth_config(request, "inst-1")
        assert "previousClient" not in public_config
        assert "old-secret" not in str(public_config)
        assert "new-secret" not in str(public_config)
        await mcp_servers.update_oauth_config(
            request, "inst-1", mcp_servers.OAuthClientConfigRequest(clientId="new-client", clientSecret="newer-secret"),
        )
    assert await resolve_client_credentials("inst-1", "user-1", cfg, issued_by="old-client") == ("old-client", "old-secret")


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [True, False])
async def test_callback_binds_issuing_client_and_reports_save_outcome(saved) -> None:
    state = CallbackCases()._state_record()
    cfg = MagicMock()
    cfg.get_config = AsyncMock(side_effect=lambda path, **kwargs: state if "oauth-states" in path else {"clientId": "cid-1", "clientSecret": "secret"})
    cfg.delete_config = AsyncMock()
    cfg.set_config = AsyncMock(return_value=saved)
    request = _mock_request(user={"userId": "user-1"}, app_state={"config_service": cfg})
    with (
        patch.object(mcp_servers.oauth_client_module, "exchange_code_for_token", AsyncMock(return_value=OAuthTokens(access_token="new"))),
        patch("app.connectors.core.base.token_service.startup_service.startup_service.get_mcp_token_refresh_service", return_value=None) as refresh_service,
    ):
        result = await mcp_servers.handle_oauth_callback(request, code="code", state="state-1", error=None)
    assert result["success"] is saved
    persisted = cfg.set_config.await_args.args[1]
    assert persisted["oauthTokens"]["clientId"] == "cid-1"
    assert persisted["credentialGeneration"]
    if saved:
        refresh_service.assert_called_once()
    else:
        assert result["error"] == "credential_save_failed"
        refresh_service.assert_not_called()


@pytest.mark.asyncio
async def test_temporary_refresh_problem_returns_503_without_marking_auth() -> None:
    cfg = MagicMock()
    request = _mock_request(user={"userId": "user-1", "orgId": "org-1"}, app_state={"config_service": cfg})
    with (
        patch.object(mcp_servers.mcp_token_refresh, "refresh_credential_record", AsyncMock(side_effect=MCPTokenRefreshTransientError("lease busy"))),
        patch.object(mcp_servers, "mark_reauth_required", AsyncMock()) as mark,
    ):
        with pytest.raises(HTTPException) as raised:
            await mcp_servers.refresh_oauth_token(request, "inst-1")
    assert raised.value.status_code == 503
    mark.assert_not_awaited()
