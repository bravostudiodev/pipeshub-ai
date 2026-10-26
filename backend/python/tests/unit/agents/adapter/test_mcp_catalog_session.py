"""Focused tests of the cache/session/authorization boundary, not the whole agent loop."""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.agent_loop.mcp_access import ResolvedMCPServer
from app.agents.agent_loop.mcp_session import MCPSessionManager
from app.agents.constants.mcp_server_constants import (
    get_mcp_credentials_path,
    get_mcp_instance_path,
)
from app.agents.mcp.catalog_cache import CatalogInvalidated, get_for_owner
from app.agents.mcp.catalog_scope import CatalogScopeError
from app.agents.mcp.client import MCPConnectionError, ToolListing
from tests.unit.agents.adapter.conftest import make_context

TOOLS = [{"name": "search", "inputSchema": {"type": "object", "properties": {}}}]


class Config:
    def __init__(self, *, oauth=False) -> None:
        self.instance = {
            "_id": "instance", "orgId": "org", "createdBy": "owner", "name": "Private MCP",
            "typeId": "private", "transport": "streamable_http", "authMode": "oauth" if oauth else "none",
            "createdAt": 0, "updatedAt": 0,
        }
        self.auth = {"isAuthenticated": True, "credentialGeneration": "grant-one", "oauthTokens": {"accessToken": "old-token"}}
        self.data = {get_mcp_instance_path("instance"): self.instance, get_mcp_credentials_path("instance", "owner"): self.auth}
        self.fail_authority = False

    async def get_config(self, key: str, default: Any = None, **kwargs: Any) -> Any:  # noqa: ANN401
        assert kwargs == {"use_cache": False, "raise_on_error": True}
        if self.fail_authority and ("/credentials/" in key or "/instances/" in key):
            raise RuntimeError("authority unavailable")
        return copy.deepcopy(self.data.get(key, default))

    async def set_config(self, key: str, value: Any, **kwargs: Any) -> bool:  # noqa: ANN401
        self.data[key] = copy.deepcopy(value)
        return True

    async def create_config_if_absent(self, key: str, value: Any, **kwargs: Any) -> bool:  # noqa: ANN401
        if key in self.data:
            return False
        self.data[key] = copy.deepcopy(value)
        return True

    async def compare_and_set_config(self, key: str, old: Any, new: Any) -> bool:  # noqa: ANN401
        if key not in self.data or self.data[key] != old:
            return False
        self.data[key] = copy.deepcopy(new)
        return True


class ProviderSession:
    def __init__(self, config, **kwargs) -> None:
        self.config = config
        self.headers = dict(kwargs.get("headers") or {})
        self.opened = self.closed = self.tools_changed = False
        self.list_calls = self.calls = 0
        self.tools = copy.deepcopy(TOOLS)
        self.on_list = None
        self.open_error = None

    async def open(self) -> None:
        await asyncio.sleep(0)
        if self.open_error:
            raise self.open_error
        self.opened = True

    @property
    def is_open(self) -> bool:
        return self.opened and not self.closed

    def update_headers(self, headers) -> None:
        self.headers.update(headers)

    async def fetch_tool_listing_in_session(self) -> ToolListing:
        self.list_calls += 1
        self.tools_changed = False
        await asyncio.sleep(0)
        if self.on_list:
            await self.on_list()
        return ToolListing(tools=copy.deepcopy(self.tools), instructions="Private instructions")

    async def call_tool_in_session(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls += 1
        return "result"

    async def aclose(self) -> None:
        self.closed = True


def harness(monkeypatch, *, oauth=False) -> SimpleNamespace:
    import app.agents.agent_loop.mcp_session as module

    config = Config(oauth=oauth)
    resolved = ResolvedMCPServer(
        instance_id="instance", name="Private MCP", display_name="Private MCP", instance=copy.deepcopy(config.instance),
        auth=copy.deepcopy(config.auth) if oauth else {}, owner_id="owner", attached_tools=None, org_id="org",
    )
    context = make_context(config_service=config, org_id="org", tool_state={})
    h = SimpleNamespace(config=config, resolved=resolved, manager=MCPSessionManager(context), made=[], on_create=None)

    def build(cfg, **kwargs) -> ProviderSession:
        session = ProviderSession(cfg, **kwargs)
        h.made.append(session)
        if h.on_create:
            h.on_create(session)
        return session

    monkeypatch.setattr(module, "MCPClientManager", build)
    return h


async def prime(h) -> None:
    async def live(scope) -> ToolListing:
        return ToolListing(tools=copy.deepcopy(TOOLS), instructions="Private instructions")
    await get_for_owner("instance", "org", "owner", h.config, live)
    await h.manager.discover_tools(h.resolved)
    assert h.made == []


@pytest.mark.asyncio
async def test_cache_miss_listing_uses_and_retains_execution_session(monkeypatch) -> None:
    h = harness(monkeypatch)
    tools = await h.manager.discover_tools(h.resolved)
    assert tools[0].name == "search"
    assert len(h.made) == 1 and h.made[0].list_calls == 1
    assert await h.manager.call(h.resolved, "search", {}) == "result"
    assert h.made[0].list_calls == 1 and h.made[0].calls == 1


@pytest.mark.asyncio
async def test_cache_hit_opens_zero_sessions_then_parallel_calls_validate_once(monkeypatch) -> None:
    h = harness(monkeypatch)
    await prime(h)
    assert await asyncio.gather(*(h.manager.call(h.resolved, "search", {}) for _ in range(3))) == ["result"] * 3
    assert len(h.made) == 1 and h.made[0].list_calls == 1 and h.made[0].calls == 3


@pytest.mark.asyncio
async def test_changed_schema_cannot_execute_on_first_or_second_attempt(monkeypatch) -> None:
    h = harness(monkeypatch)
    await prime(h)
    h.on_create = lambda session: setattr(session, "tools", [{"name": "search", "inputSchema": {"type": "object", "required": ["q"]}}])
    for _ in range(2):
        with pytest.raises(CatalogInvalidated):
            await h.manager.call(h.resolved, "search", {})
    assert h.made[0].calls == 0
    # Explicit rediscovery can adopt the new contract; the old arguments were never sent.
    await h.manager.discover_tools(h.resolved)
    assert await h.manager.call(h.resolved, "search", {"q": "safe"}) == "result"


@pytest.mark.asyncio
async def test_description_drift_does_not_refuse_a_cached_call(monkeypatch) -> None:
    h = harness(monkeypatch)
    await prime(h)

    def drift(session) -> None:
        session.tools = [{**tool, "description": "Updated 3 seconds ago"} for tool in session.tools]

    h.on_create = drift
    assert await h.manager.call(h.resolved, "search", {}) == "result"
    assert h.made[0].calls == 1


@pytest.mark.asyncio
async def test_revoke_during_validation_sends_no_tool_request(monkeypatch) -> None:
    h = harness(monkeypatch)
    await prime(h)

    async def revoke() -> None:
        h.config.data.pop(get_mcp_instance_path("instance"), None)
    h.on_create = lambda session: setattr(session, "on_list", revoke)
    with pytest.raises(CatalogScopeError):
        await h.manager.call(h.resolved, "search", {})
    assert h.made[0].calls == 0


@pytest.mark.asyncio
async def test_reconnect_during_validation_does_not_switch_the_running_call(monkeypatch) -> None:
    h = harness(monkeypatch, oauth=True)
    await prime(h)

    async def reconnect() -> None:
        h.config.auth["credentialGeneration"] = "replacement"
        h.config.auth["oauthTokens"]["accessToken"] = "different-account-token"
    h.on_create = lambda session: setattr(session, "on_list", reconnect)
    with pytest.raises(CatalogInvalidated):
        await h.manager.call(h.resolved, "search", {})
    assert h.made[0].calls == 0 and h.config.auth["isAuthenticated"]


@pytest.mark.asyncio
async def test_token_rotation_updates_healthy_headers_without_relisting_or_closing(monkeypatch) -> None:
    h = harness(monkeypatch, oauth=True)
    await h.manager.discover_tools(h.resolved)
    h.config.auth["oauthTokens"]["accessToken"] = "rotated-token"
    assert await h.manager.call(h.resolved, "search", {}) == "result"
    assert h.made[0].headers["Authorization"] == "Bearer rotated-token"
    assert h.made[0].list_calls == 1 and not h.made[0].closed


@pytest.mark.asyncio
async def test_validation_opening_401_uses_normal_oauth_recovery(monkeypatch) -> None:
    import app.agents.agent_loop.mcp_session as module

    h = harness(monkeypatch, oauth=True)
    await prime(h)
    refreshed = []

    def opening(session) -> None:
        if len(h.made) == 1:
            session.open_error = MCPConnectionError("refused", status_code=401)
    h.on_create = opening

    async def refresh(server, config_service, **_: object) -> None:
        refreshed.append(True)
        h.config.auth["oauthTokens"]["accessToken"] = "fresh-token"
        server.auth = copy.deepcopy(h.config.auth)
    monkeypatch.setattr(module, "refresh_server_credentials", refresh)
    assert await h.manager.call(h.resolved, "search", {}) == "result"
    assert refreshed == [True] and len(h.made) == 2
    assert h.made[1].calls == 1 and h.made[1].headers["Authorization"] == "Bearer fresh-token"


@pytest.mark.asyncio
async def test_authority_outage_prevents_execution_even_after_valid_cache_hit(monkeypatch) -> None:
    h = harness(monkeypatch)
    await prime(h)
    h.config.fail_authority = True
    with pytest.raises(RuntimeError, match="authority unavailable"):
        await h.manager.call(h.resolved, "search", {})
    assert h.made == []


@pytest.mark.asyncio
async def test_wrong_caller_org_is_not_taken_from_instance_metadata(monkeypatch) -> None:
    h = harness(monkeypatch)
    h.manager._context.org_id = "other-org"
    with pytest.raises(CatalogScopeError):
        await h.manager.discover_tools(h.resolved)
    assert h.made == []
