"""The new SDK must obey the fork's proxy policy without leaking credentials."""
import ipaddress
import ssl
from pathlib import Path
from unittest.mock import AsyncMock

import certifi
import httpx2
import pytest

from app.agents.mcp import url_guard, wire
from app.agents.mcp.errors import MCPUrlBlockedError
from app.utils.url_fetcher import PublicTarget, UnresolvableHostError


def test_ca_updates_are_loaded_and_invalid_ca_never_disables_verification(monkeypatch, tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text(Path(certifi.where()).read_text())
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    context = url_guard._ssl_context()
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.get_ca_certs()
    ca.write_text("not a certificate")
    with pytest.raises(ssl.SSLError):
        url_guard._ssl_context()


def target(host: str, address: str = "8.8.8.8") -> PublicTarget:
    return PublicTarget("https", host, 443, (ipaddress.ip_address(address),))


@pytest.mark.asyncio
async def test_configured_proxy_is_authoritative_and_logs_no_secrets(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://user:proxy-secret@approved.proxy:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://wrong.proxy:9999")
    monkeypatch.setattr(url_guard, "check_mcp_url", AsyncMock())
    selected, requests = [], []

    def make_transport(proxy) -> httpx2.MockTransport:
        selected.append(proxy)

        def send(request) -> httpx2.Response:
            requests.append(request)
            return httpx2.Response(401, request=request)
        return httpx2.MockTransport(send)

    monkeypatch.setattr(url_guard, "_inner_transport", make_transport)
    async with url_guard.guarded_mcp_http_client(
        "https://provider.example/mcp", allow_private=False,
        headers={"Authorization": "Bearer personal-secret"},
    ) as client:
        with wire.recording() as record:
            await client.post("https://provider.example/mcp?api_key=query-secret")
    assert selected == ["http://user:proxy-secret@approved.proxy:3128"]
    assert requests[0].url.host == "provider.example"
    assert requests[0].headers["authorization"] == "Bearer personal-secret"
    assert record.error_status == 401
    assert all(secret not in caplog.text for secret in ("personal-secret", "proxy-secret", "query-secret"))


@pytest.mark.asyncio
async def test_internal_bypass_is_direct_and_pinned_with_original_host_and_sni(monkeypatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://approved.proxy:3128")
    monkeypatch.setenv("OUTBOUND_PROXY_BYPASS", "mcp.internal.example")
    monkeypatch.setattr(url_guard, "assert_mcp_url_allowed", AsyncMock(return_value=target("mcp.internal.example", "10.0.0.5")))
    selected, sent = [], []

    def make_transport(proxy) -> httpx2.MockTransport:
        selected.append(proxy)

        def send(request) -> httpx2.Response:
            sent.append(request)
            return httpx2.Response(200, request=request)
        return httpx2.MockTransport(send)

    monkeypatch.setattr(url_guard, "_inner_transport", make_transport)
    async with url_guard.guarded_mcp_http_client("https://mcp.internal.example/mcp", allow_private=True) as client:
        await client.get("https://mcp.internal.example/mcp")
    assert selected == [None]
    assert sent[0].url.host == "10.0.0.5"
    assert sent[0].headers["host"] == "mcp.internal.example"
    assert sent[0].extensions["sni_hostname"] == "mcp.internal.example"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/mcp", "http://169.254.169.254/mcp", "http://100.100.100.200/mcp",
    "http://[::ffff:169.254.169.254]/mcp", "http://[64:ff9b::a9fe:a9fe]/mcp", "http://[fd00:ec2::254]/mcp",
])
async def test_metadata_and_loopback_are_blocked_even_for_administrator_servers(monkeypatch, url) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://approved.proxy:3128")
    sent = []

    def send(request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, request=request)

    async with url_guard.guarded_mcp_http_client(url, allow_private=True, inner=httpx2.MockTransport(send)) as client:
        with wire.recording() as record:
            response = await client.get(url)
    assert response.status_code == 502
    assert isinstance(record.unsent, MCPUrlBlockedError)
    assert sent == []


@pytest.mark.asyncio
async def test_other_origin_never_receives_authentication(monkeypatch) -> None:
    monkeypatch.delenv("OUTBOUND_PROXY_URL", raising=False)
    sent = []

    def send(request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, request=request)

    async with url_guard.guarded_mcp_http_client(
        "https://provider.example/mcp", allow_private=False, inner=httpx2.MockTransport(send),
        headers={"Authorization": "Bearer personal-secret", "X-API-Key": "personal-key"},
    ) as client:
        with wire.recording() as record:
            await client.post("https://other.example/mcp")
    assert isinstance(record.unsent, MCPUrlBlockedError)
    assert not sent


@pytest.mark.asyncio
async def test_proxy_only_dns_does_not_allow_a_direct_fallback(monkeypatch) -> None:
    async def unresolved(url, **kwargs) -> PublicTarget:
        try:
            raise UnresolvableHostError("not resolvable in this pod")
        except UnresolvableHostError as exc:
            raise MCPUrlBlockedError("not resolvable") from exc

    monkeypatch.setattr(url_guard, "assert_mcp_url_allowed", unresolved)
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://approved.proxy:3128")
    await url_guard.check_mcp_url("https://provider.example/mcp", allow_private=False)
    monkeypatch.delenv("OUTBOUND_PROXY_URL")
    with pytest.raises(MCPUrlBlockedError):
        await url_guard.check_mcp_url("https://provider.example/mcp", allow_private=False)


@pytest.mark.asyncio
async def test_squid_auth_failure_is_not_a_rejected_user_credential(monkeypatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", "http://approved.proxy:3128")
    monkeypatch.setattr(url_guard, "check_mcp_url", AsyncMock())
    transport = httpx2.MockTransport(lambda request: httpx2.Response(401, headers={"X-Squid-Error": "ERR_ACCESS_DENIED"}, request=request))
    async with url_guard.guarded_mcp_http_client("https://provider.example/mcp", allow_private=False, inner=transport) as client:
        with wire.recording() as record:
            await client.get("https://provider.example/mcp")
    assert isinstance(record.unsent, MCPUrlBlockedError)
