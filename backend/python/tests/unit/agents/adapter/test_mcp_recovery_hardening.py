"""Recover failures before execution without replaying ambiguous tool calls."""
from unittest.mock import AsyncMock

import pytest

from app.agent_loop_lib.tools.registry import ToolRegistry
from app.agents.agent_loop import mcp_session, mcp_tool_loader
from app.agents.agent_loop.mcp_session import MCPSessionManager
from app.agents.agent_loop.mcp_tool_loader import MCPToolProvider
from app.agents.mcp.client import MCPCallInterruptedError, MCPConnectionError
from app.agents.mcp.models import MCPToolInfo, OAuthTokens
from app.agents.mcp.oauth_client import MCPRefreshTokenInvalidError
from tests.unit.agents.adapter.conftest import make_context
from tests.unit.agents.adapter.test_mcp_session import (
    _FakeClientManager,
    _FakeClientManagerFactory,
    _server,
)
from tests.unit.agents.adapter.test_mcp_session import (
    _isolate_policy_authority as _isolate_policy_authority,
)
from tests.unit.agents.adapter.test_mcp_tool_loader import (
    _context_with_server,
    _discover_ok,
)

pytestmark = pytest.mark.usefixtures("stub_mcp_discovery")


@pytest.mark.asyncio
async def test_opening_401_refreshes_before_sending_the_tool(monkeypatch) -> None:
    factory = _FakeClientManagerFactory()
    monkeypatch.setattr(mcp_session, "MCPClientManager", factory)
    context = make_context()
    manager = MCPSessionManager(context)
    server = _server(auth_mode="oauth")
    server.auth = {"connectedAt": 123}
    original = manager._build_and_open
    attempts = 0

    async def open_session(server) -> _FakeClientManager:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise MCPConnectionError("refused", status_code=401)
        return await original(server)

    monkeypatch.setattr(manager, "_build_and_open", open_session)
    refresh = AsyncMock(return_value=OAuthTokens(access_token="fresh"))
    monkeypatch.setattr(mcp_session, "refresh_credential_record", refresh)
    assert await manager.call(server, "search", {}) == "ok"
    refresh.assert_awaited_once()
    assert attempts == 2
    assert factory.built[0].calls == [("search", {})]
    assert server.auth["connectedAt"] == 123


@pytest.mark.asyncio
async def test_opening_timeout_retries_but_call_timeout_does_not(monkeypatch) -> None:
    factory = _FakeClientManagerFactory()
    monkeypatch.setattr(mcp_session, "MCPClientManager", factory)
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_session.asyncio, "sleep", sleep)
    manager = MCPSessionManager(make_context())
    original = manager._build_and_open
    attempts = 0

    async def open_session(server) -> _FakeClientManager:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("opening timed out")
        result = await original(server)
        result.responses = [TimeoutError("call timed out")]
        return result

    monkeypatch.setattr(manager, "_build_and_open", open_session)
    with pytest.raises(MCPCallInterruptedError, match="do not repeat"):
        await manager.call(_server(), "change_record", {})
    assert attempts == 2
    assert factory.built[0].calls == [("change_record", {})]
    sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_one_discovery_blip_recovers_without_user_action(monkeypatch) -> None:
    context = _context_with_server()
    registry = ToolRegistry()
    attempts = 0

    async def discover(config, credentials, timeout_seconds) -> list[MCPToolInfo]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise MCPConnectionError("connection reset")
        return await _discover_ok(config, credentials, timeout_seconds)

    monkeypatch.setattr(mcp_tool_loader, "discover_tools", discover)
    monkeypatch.setattr(mcp_tool_loader.asyncio, "sleep", AsyncMock())
    mark = AsyncMock()
    monkeypatch.setattr(mcp_tool_loader, "mark_reauth_required", mark)
    await MCPToolProvider().load_into(registry, context)
    assert attempts == 2
    assert context.mcp_tool_load_failures == []
    assert registry.has("mcp_jira_mcp_search")
    mark.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_permanent_refresh_rejection_passes_snapshot(monkeypatch) -> None:
    context = _context_with_server()
    context.mcp_server_configs["inst-1"]["instance"]["authMode"] = "oauth"
    snapshot = {"isAuthenticated": True, "oauthTokens": {"accessToken": "old"}}
    error = MCPRefreshTokenInvalidError("invalid_grant")
    error.rejected_auth = snapshot
    monkeypatch.setattr(mcp_tool_loader, "discover_tools", AsyncMock(side_effect=MCPConnectionError("refused", status_code=401)))
    monkeypatch.setattr(mcp_tool_loader, "refresh_server_credentials", AsyncMock(side_effect=error))
    mark = AsyncMock(return_value=True)
    monkeypatch.setattr(mcp_tool_loader, "mark_reauth_required", mark)
    await MCPToolProvider().load_into(ToolRegistry(), context)
    assert mark.await_args.kwargs["expected_auth"] == snapshot
    assert context.mcp_tool_load_failures[0]["reason"] == "reauth_required"
