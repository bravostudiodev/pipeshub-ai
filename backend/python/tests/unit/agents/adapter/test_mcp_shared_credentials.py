"""Shared administrator credentials are refused explicitly, never reported as a temporary outage.

Runs the real discovery path (no `stub_mcp_discovery`): the refusal happens in
`load_catalog_scope`, before any connection is made.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.agent_loop_lib.tools.registry import ToolRegistry
from app.agents.agent_loop.mcp_tool_loader import MCPToolProvider
from app.agents.mcp.models import MCPAuthMode, MCPServerInstanceConfig, MCPTransport
from app.agents.mcp.service import SHARED_CREDENTIALS_UNSUPPORTED_MESSAGE
from app.api.routes.mcp_servers import _validate_instance_config
from app.modules.agents.capability_summary import _build_mcp_failures_section
from tests.unit.agents.adapter.conftest import make_context

_INSTANCE = {
    "_id": "inst-1", "orgId": "org-1", "createdBy": "admin-1", "name": "Docs", "typeId": None,
    "transport": "streamable_http", "url": "https://docs.example.com/mcp", "authMode": "api_token",
    "useAdminAuth": True, "createdAt": 0, "updatedAt": 0,
}


def _context() -> Any:  # noqa: ANN401
    context = make_context(
        mcp_servers=[{"instanceId": "inst-1", "name": "Docs", "displayName": "Docs"}],
        mcp_server_configs={"inst-1": {
            "instance": dict(_INSTANCE),
            "auth": {"isAuthenticated": True, "credentials": {"apiToken": "shared-secret-token"}},
            "ownerId": "user-1",
        }},
    )

    async def get_config(path: str, default: Any = None, **_: Any) -> Any:  # noqa: ANN401
        return dict(_INSTANCE) if path.endswith("/inst-1") else default

    context.config_service.get_config = AsyncMock(side_effect=get_config)
    return context


@pytest.mark.asyncio
async def test_discovery_reports_shared_credentials_not_a_temporary_failure() -> None:
    context = _context()

    await MCPToolProvider().load_into(ToolRegistry(), context)

    assert context.mcp_tool_load_failures == [
        {"instanceId": "inst-1", "name": "Docs", "reason": "shared_credentials_unsupported"},
    ]
    parts: list[str] = []
    _build_mcp_failures_section({"mcp_tool_load_failures": context.mcp_tool_load_failures}, parts=parts)
    summary = "\n".join(parts)
    assert "per-user sign-in" in summary
    assert "temporarily" not in summary


@pytest.mark.parametrize("auth_mode", [MCPAuthMode.API_TOKEN, MCPAuthMode.HEADERS])
def test_admins_cannot_save_a_shared_token_instance(auth_mode: MCPAuthMode) -> None:
    payload = MCPServerInstanceConfig(
        name="Docs", transport=MCPTransport.STREAMABLE_HTTP, auth_mode=auth_mode,
        use_admin_auth=True, url="https://docs.example.com/mcp",
    )
    with pytest.raises(HTTPException) as raised:
        _validate_instance_config(payload, registry=None)  # type: ignore[arg-type]
    assert raised.value.status_code == 400
    assert raised.value.detail == SHARED_CREDENTIALS_UNSUPPORTED_MESSAGE
