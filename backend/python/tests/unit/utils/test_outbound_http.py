"""Outbound routing and logging across the HTTP libraries the services use.

A loopback server stands in for the forward proxy (its request line shows what the client
asked it to fetch) and another for an in-cluster service. External destinations are
documentation addresses that nothing listens on: only the fake proxy is ever contacted.
"""

import json
import logging
import os
import socket
from collections.abc import Iterator

import aiohttp
import httpx
import pytest
import requests

from app.utils import outbound_http
from app.utils.outbound_http import (
    install_outbound_http,
    log_denied,
    outbound_category,
    tag_client,
)
from app.utils.outbound_proxy import proxy_environment
from app.utils.request_context import reset_context, set_context
from tests.unit.utils.outbound_fakes import FakeServer

EXTERNAL = "203.0.113.10"
SECRETS = ("s3cr3t-token", "sk-live-key", "hunter2", "session=abc", "/private/path", "api_key")


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith("outbound_http "):
            self.events.append(json.loads(message.removeprefix("outbound_http ")))


@pytest.fixture
def proxy() -> Iterator[FakeServer]:
    server = FakeServer(body=b"via-proxy")
    yield server
    server.close()


@pytest.fixture
def service() -> Iterator[FakeServer]:
    server = FakeServer(body=b"direct")
    yield server
    server.close()


@pytest.fixture
def events(proxy: FakeServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Capture]:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("OUTBOUND_PROXY_URL", f"http://user:hunter2@127.0.0.1:{proxy.port}")
    os.environ.update(proxy_environment())
    install_outbound_http()
    capture = _Capture()
    logger = logging.getLogger("outbound_http")
    logger.addHandler(capture)
    yield capture
    logger.removeHandler(capture)


def _fake_dns(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    real = socket.getaddrinfo

    def getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        if host == "127.0.0.1":
            return real(host, *args, **kwargs)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def _only(capture: _Capture, **match: object) -> dict:
    found = [e for e in capture.events if all(e.get(k) == v for k, v in match.items())]
    assert len(found) == 1, capture.events
    return found[0]


def _assert_nothing_sensitive(capture: _Capture) -> None:
    text = json.dumps(capture.events)
    for secret in SECRETS:
        assert secret not in text


async def test_httpx_external_request_goes_through_the_proxy(
    events: _Capture, proxy: FakeServer
) -> None:
    url = f"http://{EXTERNAL}:8080/private/path?api_key=s3cr3t-token"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers={"Authorization": "Bearer sk-live-key", "Cookie": "session=abc"})

    assert response.text == "via-proxy"
    assert proxy.request_lines == [f"GET {url} HTTP/1.1"]
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["route_reason"], event["outcome"], event["status"]) == (
        "proxy", "external", "response", 200,
    )
    assert event["dest_port"] == 8080
    assert event["method"] == "GET"
    assert event["proxy"] == f"127.0.0.1:{proxy.port}"
    assert "hunter2" not in json.dumps(event)
    _assert_nothing_sensitive(events)


async def test_httpx_in_cluster_request_bypasses_the_proxy(
    events: _Capture, proxy: FakeServer, service: FakeServer
) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{service.url}/internal/index?token=s3cr3t-token", json={"a": 1})

    assert response.text == "direct"
    assert proxy.request_lines == []
    assert service.request_lines[0].startswith("POST /internal/index")
    event = _only(events, dest_host="127.0.0.1")
    assert (event["via"], event["route_reason"], event["status"]) == ("direct", "in_cluster", 200)
    assert event["dest_port"] == service.port
    _assert_nothing_sensitive(events)


async def test_httpx_dotless_service_name_stays_direct_even_though_no_proxy_cannot_say_so(
    events: _Capture,
) -> None:
    async with httpx.AsyncClient() as client:
        transport = client._transport_for_url(httpx.URL("http://qdrant:6333/collections"))
        assert transport is client._transport
        external = client._transport_for_url(httpx.URL(f"http://{EXTERNAL}/"))
        assert external is not client._transport


async def test_httpx_explicit_client_proxy_is_left_alone(events: _Capture, proxy: FakeServer) -> None:
    other = FakeServer(body=b"other")
    try:
        async with httpx.AsyncClient(proxy=other.url) as client:
            await client.get("http://qdrant:6333/x")
        assert other.request_lines == ["GET http://qdrant:6333/x HTTP/1.1"]
        assert proxy.request_lines == []
    finally:
        other.close()


async def test_proxy_failure_is_logged_as_a_proxy_error(
    events: _Capture, proxy: FakeServer
) -> None:
    with pytest.raises(httpx.ProxyError):
        async with httpx.AsyncClient() as client:
            await client.get(f"https://{EXTERNAL}/v1/models")

    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["outcome"], event["error_type"]) == ("proxy", "proxy_error", "ProxyError")
    assert "status" not in event
    assert proxy.request_lines == [f"CONNECT {EXTERNAL}:443 HTTP/1.1"]


async def test_connection_failure_is_logged(events: _Capture, service: FakeServer) -> None:
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()
    with pytest.raises(httpx.ConnectError):
        async with httpx.AsyncClient() as client:
            await client.get(f"http://127.0.0.1:{port}/")
    event = _only(events, dest_port=port)
    assert (event["via"], event["outcome"]) == ("direct", "connect_error")


async def test_request_id_from_the_trace_context_is_logged(events: _Capture) -> None:
    token = set_context("user1-req42")
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"http://{EXTERNAL}/")
    finally:
        reset_context(token)
    # the service suffix (e.g. "-es") is appended to the root id
    assert _only(events, dest_host=EXTERNAL)["request_id"].startswith("user1-req42")


async def test_request_without_a_trace_context_has_no_request_id(events: _Capture) -> None:
    async with httpx.AsyncClient() as client:
        await client.get(f"http://{EXTERNAL}/")
    assert "request_id" not in _only(events, dest_host=EXTERNAL)


async def test_each_redirect_hop_is_logged_with_its_own_route(
    events: _Capture, proxy: FakeServer, service: FakeServer
) -> None:
    proxy.respond_with(302, Location=f"{service.url}/final")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(f"http://{EXTERNAL}/start")

    assert response.text == "direct"
    first, second = events.events
    assert (first["dest_host"], first["via"], first["status"]) == (EXTERNAL, "proxy", 302)
    assert (second["dest_port"], second["via"], second["status"]) == (service.port, "direct", 200)


async def test_aiohttp_external_request_is_proxied_and_logged(
    events: _Capture, proxy: FakeServer
) -> None:
    url = f"http://{EXTERNAL}/private/path?api_key=s3cr3t-token"
    async with aiohttp.ClientSession() as session, session.get(url, headers={"Authorization": "Bearer sk-live-key"}) as response:
        assert await response.text() == "via-proxy"

    assert proxy.request_lines[0].startswith(f"GET {url}")
    assert b"Proxy-Authorization: Basic" in proxy.raw_requests[0]
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["route_reason"], event["status"]) == ("proxy", "external", 200)
    _assert_nothing_sensitive(events)


async def test_aiohttp_in_cluster_request_is_direct(
    events: _Capture, proxy: FakeServer, service: FakeServer
) -> None:
    async with aiohttp.ClientSession(trust_env=True) as session, session.get(f"{service.url}/x") as response:
        assert await response.text() == "direct"
    assert proxy.request_lines == []
    assert _only(events, dest_port=service.port)["via"] == "direct"


async def test_aiohttp_failure_is_logged(events: _Capture, proxy: FakeServer) -> None:
    with pytest.raises(aiohttp.ClientHttpProxyError):
        async with aiohttp.ClientSession() as session, session.get(f"https://{EXTERNAL}/"):
            pass
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["outcome"]) == ("proxy", "proxy_error")


def test_requests_external_request_is_proxied_and_logged(events: _Capture, proxy: FakeServer) -> None:
    url = f"http://{EXTERNAL}/private/path?api_key=s3cr3t-token"
    response = requests.get(url, headers={"Authorization": "Bearer sk-live-key"}, timeout=5)
    assert response.text == "via-proxy"
    assert proxy.request_lines[0].startswith(f"GET {url}")
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["status"]) == ("proxy", 200)
    _assert_nothing_sensitive(events)


def test_requests_in_cluster_request_is_direct(
    events: _Capture, proxy: FakeServer, service: FakeServer
) -> None:
    assert requests.get(f"{service.url}/x", timeout=5).text == "direct"
    assert proxy.request_lines == []
    assert _only(events, dest_port=service.port)["via"] == "direct"


def test_requests_in_cluster_wins_over_an_environment_proxy_that_would_match(
    events: _Capture, proxy: FakeServer
) -> None:
    other = FakeServer(body=b"direct")
    try:
        os.environ["NO_PROXY"] = ""  # the library alone would proxy this destination
        assert requests.get(f"{other.url}/x", timeout=5).text == "direct"
    finally:
        other.close()
    assert proxy.request_lines == []


def test_requests_proxy_error_is_logged(events: _Capture, proxy: FakeServer) -> None:
    with pytest.raises(requests.exceptions.ProxyError):
        requests.get(f"https://{EXTERNAL}/", timeout=5)
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["outcome"]) == ("proxy", "proxy_error")


def test_urllib_request_is_logged(events: _Capture, proxy: FakeServer) -> None:
    import urllib.request

    with urllib.request.urlopen(f"http://{EXTERNAL}/x?token=s3cr3t-token", timeout=5) as response:
        assert response.read() == b"via-proxy"
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["status"]) == ("proxy", 200)
    _assert_nothing_sensitive(events)


async def test_openai_sdk_client_is_routed_and_logged_as_a_model_client(
    events: _Capture, proxy: FakeServer
) -> None:
    import openai

    proxy._body, proxy._content_type = b'{"object":"list","data":[]}', "application/json"
    client = openai.AsyncOpenAI(base_url=f"http://{EXTERNAL}/v1", api_key="sk-live-key", max_retries=0)
    await client.models.list()
    await client.close()

    event = _only(events, dest_host=EXTERNAL)
    assert (event["category"], event.get("sdk"), event["via"]) == ("http", None, "proxy")
    assert proxy.request_lines[0].startswith(f"GET http://{EXTERNAL}/v1/models")
    _assert_nothing_sensitive(events)


async def test_unknown_sdk_gets_the_sdk_category(events: _Capture) -> None:
    client = httpx.AsyncClient()
    client._outbound_category = "sdk"
    async with client:
        await client.get(f"http://{EXTERNAL}/")
    assert _only(events, dest_host=EXTERNAL)["category"] == "sdk"


async def test_explicit_category_overrides_inference(events: _Capture) -> None:
    with outbound_category("oauth"):
        async with httpx.AsyncClient() as client:
            await client.get(f"http://{EXTERNAL}/")
    assert _only(events, dest_host=EXTERNAL)["category"] == "oauth"

    async with httpx.AsyncClient() as client:
        tag_client(client, "mcp")
        await client.get(f"http://{EXTERNAL}:81/")
    assert _only(events, dest_port=81)["category"] == "mcp"


async def test_proxy_not_applied_is_flagged_when_a_client_goes_around_the_proxy(
    events: _Capture, proxy: FakeServer
) -> None:
    mock = httpx.MockTransport(lambda request: httpx.Response(200))
    async with httpx.AsyncClient(transport=mock) as client:
        await client.get(f"http://{EXTERNAL}/")
    event = _only(events, dest_host=EXTERNAL)
    assert (event["via"], event["route_reason"]) == ("direct", "proxy_not_applied")


def test_denied_requests_are_logged_without_the_path_or_the_resolved_address(events: _Capture) -> None:
    log_denied("http://169.254.169.254/latest/meta-data?token=s3cr3t-token", "blocked_address", category="url_fetch")
    event = _only(events, outcome="denied")
    assert (event["dest_host"], event["category"], event["route_reason"]) == (
        "169.254.169.254", "url_fetch", "blocked_address",
    )
    _assert_nothing_sensitive(events)


def test_destination_drops_userinfo_path_and_query() -> None:
    assert outbound_http.destination("https://u:hunter2@api.example.com/a/b?api_key=s3cr3t-token#x") == (
        "api.example.com", 443,
    )
    assert outbound_http.destination("http://[2606:4700::1]:8080/") == ("2606:4700::1", 8080)
    assert outbound_http.destination("http://[bad") == ("unparseable", None)


async def test_install_is_idempotent_and_logs_each_request_once(events: _Capture) -> None:
    install_outbound_http()
    install_outbound_http()
    async with httpx.AsyncClient() as client:
        await client.get(f"http://{EXTERNAL}/")
    _only(events, dest_host=EXTERNAL)


async def test_mcp_client_factory_requests_are_categorised_and_proxied(
    events: _Capture, proxy: FakeServer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from app.agents.mcp import url_guard

    monkeypatch.setattr(url_guard, "check_mcp_url", AsyncMock())
    client = url_guard.guarded_mcp_http_client(
        f"http://{EXTERNAL}/mcp", allow_private=False, headers={"Authorization": "Bearer sk-live-key"},
    )
    async with client:
        await client.post(f"http://{EXTERNAL}/mcp?token=s3cr3t-token", json={"jsonrpc": "2.0"})

    event = _only(events, dest_host=EXTERNAL)
    assert (event["category"], event["via"], event["method"], event["status"]) == (
        "mcp", "proxy", "POST", 200,
    )
    _assert_nothing_sensitive(events)


async def test_mcp_client_to_an_in_cluster_server_is_direct(
    events: _Capture, proxy: FakeServer, service: FakeServer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ipaddress
    from unittest.mock import AsyncMock

    from app.agents.mcp import url_guard
    from app.utils.url_fetcher import PublicTarget

    target = PublicTarget("http", "127.0.0.1", service.port, (ipaddress.ip_address("127.0.0.1"),))
    monkeypatch.setattr(url_guard, "assert_mcp_url_allowed", AsyncMock(return_value=target))
    async with url_guard.guarded_mcp_http_client(f"{service.url}/mcp", allow_private=True) as client:
        await client.get(f"{service.url}/mcp")
    assert proxy.request_lines == []
    assert _only(events, dest_port=service.port)["category"] == "mcp"


async def test_oauth_token_exchange_goes_through_the_proxy_without_logging_secrets(
    events: _Capture, proxy: FakeServer
) -> None:
    from app.agents.mcp.oauth_client import (
        exchange_code_for_token,
        refresh_access_token,
    )

    proxy._body, proxy._content_type = b'{"access_token":"at","expires_in":60}', "application/json"
    tokens = await exchange_code_for_token(
        f"http://{EXTERNAL}/oauth/token", "client-id", "hunter2", "auth-code-123", "https://app/cb", "verifier-xyz"
    )
    await refresh_access_token(f"http://{EXTERNAL}/oauth/token", "client-id", "hunter2", "refresh-tok-456")

    assert tokens.access_token == "at"
    assert [line.split(" HTTP")[0] for line in proxy.request_lines] == [f"POST http://{EXTERNAL}/oauth/token"] * 2
    assert b"auth-code-123" in proxy.raw_requests[0]  # the proxy gets the body; the log does not
    assert [e["category"] for e in events.events] == ["http", "http"]
    assert all(e["via"] == "proxy" for e in events.events)
    text = json.dumps(events.events)
    for secret in (*SECRETS, "auth-code-123", "verifier-xyz", "refresh-tok-456", "client-id"):
        assert secret not in text


async def test_oauth_token_endpoint_inside_the_cluster_is_direct(
    events: _Capture, proxy: FakeServer, service: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.agents.mcp import oauth_client
    from app.agents.mcp.oauth_client import exchange_code_for_token

    # The fake server listens on loopback, which the token URL policy refuses; a real
    # in-cluster endpoint is a private address. This test is about routing, not that policy.
    monkeypatch.setattr(oauth_client, "_check_token_url", AsyncMock())

    service._body, service._content_type = b'{"access_token":"at"}', "application/json"
    await exchange_code_for_token(f"{service.url}/token", "id", None, "code", "https://app/cb")
    assert proxy.request_lines == []
    assert _only(events, dest_port=service.port)["via"] == "direct"


async def test_oauth_discovery_and_registration_use_the_proxy(
    events: _Capture, proxy: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.mcp import dcr

    _fake_dns(monkeypatch, "93.184.215.14")
    proxy._body, proxy._content_type = b'{"client_id":"registered"}', "application/json"
    client = await dcr.register_dynamic_client(
        "http://auth.example.com/register", "OddJeeves", "https://app/cb", "http://auth.example.com/authorize",
        "http://auth.example.com/token",
    )
    assert client.client_id == "registered"
    assert proxy.request_lines == ["POST http://auth.example.com/register HTTP/1.1"]
    event = _only(events, dest_host="auth.example.com")
    assert (event["category"], event["via"], event["status"]) == ("http", "proxy", 200)


async def test_oauth_discovery_of_a_private_target_is_denied_and_logged(
    events: _Capture, proxy: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.mcp import dcr

    _fake_dns(monkeypatch, "169.254.169.254")
    with pytest.raises(dcr.DiscoveryBlockedError):
        await dcr.assert_discovery_target_allowed("https://metadata.example.com/.well-known/x?token=s3cr3t-token")
    assert proxy.request_lines == []
    event = _only(events, outcome="denied")
    assert (event["category"], event["dest_host"], event["route_reason"]) == (
        "oauth", "metadata.example.com", "blocked_address",
    )
    _assert_nothing_sensitive(events)
