"""HTTP failures belong to one operation, never the previous listener or a sibling."""
import asyncio
from unittest.mock import AsyncMock

import httpx2
import pytest

from app.agents.mcp import client as client_module
from app.agents.mcp import url_guard, wire
from app.agents.mcp.errors import MCPHttpStatusError, MCPRequestNotSentError


@pytest.mark.asyncio
async def test_listener_status_cannot_classify_an_unrelated_connect_failure(monkeypatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://proxy.example:3128")
    monkeypatch.setattr(url_guard, "check_mcp_url", AsyncMock())

    async def respond(request) -> httpx2.Response:
        if request.method == "GET":
            return httpx2.Response(405, request=request)
        raise httpx2.ConnectError("connection reset before send", request=request)

    async with url_guard.guarded_mcp_http_client(
        "https://example.test/mcp", allow_private=False, inner=httpx2.MockTransport(respond),
    ) as client:
        with wire.recording() as listener:
            await client.get("https://example.test/mcp")
        with wire.recording() as operation:
            await client.post("https://example.test/mcp")
    assert listener.error_status == 405
    assert isinstance(client_module._wire_failure(operation, what="call"), MCPRequestNotSentError)


@pytest.mark.asyncio
async def test_parallel_requests_have_independent_auth_and_success_records(monkeypatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://proxy.example:3128")
    monkeypatch.setattr(url_guard, "check_mcp_url", AsyncMock())

    async def respond(request) -> httpx2.Response:
        await asyncio.sleep(0)
        return httpx2.Response(401 if request.url.path.endswith("refused") else 200, request=request)

    async with url_guard.guarded_mcp_http_client(
        "https://example.test/mcp", allow_private=False, inner=httpx2.MockTransport(respond),
    ) as client:
        async def run(path) -> wire.WireRecord:
            with wire.recording() as record:
                await client.post("https://example.test/" + path)
                return record

        refused, accepted = await asyncio.gather(run("refused"), run("accepted"))
    assert isinstance(client_module._wire_failure(refused, what="call"), MCPHttpStatusError)
    assert refused.error_status == 401
    assert accepted.statuses == [200]
    assert client_module._wire_failure(accepted, what="call") is None
