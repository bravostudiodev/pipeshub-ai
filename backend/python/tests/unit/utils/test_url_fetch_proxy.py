"""URL fetching through the outbound proxy keeps the SSRF guarantees.

Each hop is still resolved and checked here, and the proxy is handed the validated address
instead of the hostname so it has nothing to resolve again. DNS is faked; the fake proxy
records the request line it receives.
"""

import json
import logging
import os
import socket
from collections.abc import Iterator

import pytest

from app.utils import url_fetcher
from app.utils.outbound_http import install_outbound_http
from app.utils.outbound_proxy import proxy_environment
from app.utils.public_http import PublicFetchError, PublicFetchLimits, PublicUrlFetcher, UnsafeUrlError
from app.utils.url_fetcher import FetchError, fetch_url
from tests.unit.utils.outbound_fakes import FakeServer
from tests.unit.utils.test_outbound_http import _Capture

PUBLIC_IP = "93.184.215.14"
_DNS = {
    "example.com": [PUBLIC_IP],
    "internal.example.com": ["10.0.0.5"],
    "rebind.example.com": ["93.184.215.20", "169.254.169.254"],
}
LIMITS = PublicFetchLimits(max_bytes=1024)


@pytest.fixture(autouse=True)
def _fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        if host == "127.0.0.1":  # the fake proxy itself
            return real_getaddrinfo(host, *args, **kwargs)
        if host not in _DNS:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in _DNS[host]]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def proxy() -> Iterator[FakeServer]:
    server = FakeServer(body=b"<html>fetched</html>", content_type="text/html")
    yield server
    server.close()


@pytest.fixture
def events(proxy: FakeServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Capture]:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("OUTBOUND_PROXY_URL", proxy.url)
    os.environ.update(proxy_environment())
    install_outbound_http()
    capture = _Capture()
    logging.getLogger("outbound_http").addHandler(capture)
    yield capture
    logging.getLogger("outbound_http").removeHandler(capture)


def test_http_hop_sends_the_proxy_the_validated_address_not_the_hostname(
    events: _Capture, proxy: FakeServer
) -> None:
    result = fetch_url("http://example.com/page?token=s3cr3t-token", strategy="requests")

    assert result.status_code == 200
    assert proxy.request_lines == [f"GET http://{PUBLIC_IP}/page?token=s3cr3t-token HTTP/1.1"]
    assert b"Host: example.com" in proxy.raw_requests[0]
    assert "example.com" not in proxy.request_lines[0]
    event = events.events[-1]
    assert (event["dest_host"], event["via"], event["status"]) == ("example.com", "proxy", 200)
    assert "s3cr3t-token" not in json.dumps(events.events)


def test_https_hop_tunnels_to_the_validated_address(events: _Capture, proxy: FakeServer) -> None:
    proxy._connect_status = 403
    with pytest.raises(FetchError):
        fetch_url("https://example.com/", strategy="requests")  # the fake proxy refuses CONNECT
    assert proxy.request_lines == [f"CONNECT {PUBLIC_IP}:443 HTTP/1.1"]
    assert "example.com" not in proxy.request_lines[0]
    proxied = [e for e in events.events if e["outcome"] == "proxy_error"]
    assert proxied and proxied[0]["via"] == "proxy"
    assert _only_denied(events)["route_reason"] == "proxy_denied"


def test_proxied_fetch_never_runs_the_curl_strategies(
    events: _Capture, proxy: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # curl would hand the proxy the hostname (CURLOPT_RESOLVE does not bind a proxied destination).
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("curl_cffi must not run when the hop is proxied")

    monkeypatch.setattr(url_fetcher, "_try_curl_cffi", forbidden)
    assert fetch_url("http://example.com/", strategy="curl_cffi_h2").status_code == 200
    assert fetch_url("http://example.com/").status_code == 200
    assert all(line.startswith(f"GET http://{PUBLIC_IP}/") for line in proxy.request_lines)


@pytest.mark.parametrize("host", ["internal.example.com", "rebind.example.com"])
def test_private_targets_are_refused_before_the_proxy_is_contacted(
    events: _Capture, proxy: FakeServer, host: str
) -> None:
    with pytest.raises(FetchError):
        fetch_url(f"http://{host}/admin?token=s3cr3t-token")
    assert proxy.request_lines == []
    event = _only_denied(events)
    assert (event["dest_host"], event["category"], event["route_reason"]) == (host, "http", "blocked_address")
    assert "s3cr3t-token" not in json.dumps(events.events)


def test_literal_private_and_metadata_addresses_are_refused(events: _Capture, proxy: FakeServer) -> None:
    for url in ("http://169.254.169.254/latest/meta-data", "http://127.0.0.1:8088/", "http://[::1]/"):
        with pytest.raises(FetchError):
            fetch_url(url)
    assert proxy.request_lines == []
    assert len([e for e in events.events if e["outcome"] == "denied"]) == 3


def test_unresolvable_host_is_refused_not_passed_to_the_proxy(events: _Capture, proxy: FakeServer) -> None:
    # Fail closed: the local check needs an answer even though the proxy could resolve the name.
    with pytest.raises(FetchError):
        fetch_url("http://nxdomain.example.net/")
    assert proxy.request_lines == []
    assert _only_denied(events)["route_reason"] == "unresolvable_host"


def test_redirect_to_a_private_host_is_refused_at_the_hop(events: _Capture, proxy: FakeServer) -> None:
    proxy.respond_with(302, Location="http://internal.example.com/secret")
    with pytest.raises(FetchError):
        fetch_url("http://example.com/start", strategy="requests")
    assert proxy.request_lines == [f"GET http://{PUBLIC_IP}/start HTTP/1.1"]
    assert _only_denied(events)["dest_host"] == "internal.example.com"


def test_environment_proxies_are_still_ignored_without_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoy = FakeServer()
    try:
        monkeypatch.delenv("OUTBOUND_PROXY_URL", raising=False)
        monkeypatch.setenv("HTTP_PROXY", decoy.url)
        monkeypatch.setenv("http_proxy", decoy.url)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        with pytest.raises(FetchError):
            fetch_url("http://example.com/", strategy="requests", timeout=1)  # nothing listens on :80
        assert decoy.request_lines == []
    finally:
        decoy.close()


async def test_public_url_fetcher_http_hop_goes_to_the_proxy_with_the_validated_address(
    events: _Capture, proxy: FakeServer
) -> None:
    response = await PublicUrlFetcher().get("http://example.com/skill.zip?sig=s3cr3t-token", LIMITS)

    assert response.status_code == 200 and response.content == b"<html>fetched</html>"
    assert proxy.request_lines == [f"GET http://{PUBLIC_IP}/skill.zip?sig=s3cr3t-token HTTP/1.1"]
    assert b"Host: example.com" in proxy.raw_requests[0]
    event = events.events[-1]
    assert (event["dest_host"], event["via"], event["category"]) == (PUBLIC_IP, "proxy", "http")
    assert "s3cr3t-token" not in json.dumps(events.events)


async def test_public_url_fetcher_https_hop_tunnels_to_the_validated_address(
    events: _Capture, proxy: FakeServer
) -> None:
    with pytest.raises(PublicFetchError):
        await PublicUrlFetcher().get("https://example.com/x", LIMITS)
    assert proxy.request_lines == [f"CONNECT {PUBLIC_IP}:443 HTTP/1.1"]


async def test_public_url_fetcher_refuses_private_targets_without_touching_the_proxy(
    events: _Capture, proxy: FakeServer
) -> None:
    with pytest.raises(UnsafeUrlError):
        await PublicUrlFetcher().get("http://internal.example.com/", LIMITS)
    assert proxy.request_lines == []
    assert _only_denied(events)["dest_host"] == "internal.example.com"


def _only_denied(capture: _Capture) -> dict:
    denied = [e for e in capture.events if e["outcome"] == "denied"]
    assert len(denied) == 1, capture.events
    return denied[0]


def test_proxy_that_refuses_the_ip_tunnel_fails_closed_and_logs(
    events: _Capture, proxy: FakeServer
) -> None:
    """A Squid hostname allowlist cannot match ``CONNECT <validated ip>:443``."""
    proxy._connect_status = 403
    with pytest.raises(FetchError, match="outbound proxy refused"):
        fetch_url("https://example.com/", strategy="requests")
    assert proxy.request_lines and all(line.startswith(f"CONNECT {PUBLIC_IP}:443") for line in proxy.request_lines)
    denied = _only_denied(events)
    assert (denied["route_reason"], denied["category"], denied["dest_host"]) == ("proxy_denied", "http", "example.com")


def test_squid_access_denied_page_on_a_plain_http_hop_fails_closed(events: _Capture, proxy: FakeServer) -> None:
    proxy.respond_with(403, **{"X-Squid-Error": "ERR_ACCESS_DENIED 0"})
    with pytest.raises(FetchError, match="outbound proxy refused"):
        fetch_url("http://example.com/", strategy="requests")
    assert _only_denied(events)["route_reason"] == "proxy_denied"


def test_origin_403_is_not_mistaken_for_a_proxy_denial(events: _Capture, proxy: FakeServer) -> None:
    proxy.respond_with(403)  # no Squid error header: the origin said no
    with pytest.raises(FetchError, match="No error details"):
        fetch_url("http://example.com/forbidden", strategy="requests")
    assert not [e for e in events.events if e["outcome"] == "denied"]


async def test_public_url_fetcher_fails_closed_when_the_proxy_refuses(
    events: _Capture, proxy: FakeServer
) -> None:
    proxy._connect_status = 403
    with pytest.raises(UnsafeUrlError, match="outbound proxy refused"):
        await PublicUrlFetcher().get("https://example.com/x", LIMITS)
    assert all(line.startswith("CONNECT ") for line in proxy.request_lines)
    assert _only_denied(events)["route_reason"] == "proxy_denied"


async def test_public_url_fetcher_squid_error_page_fails_closed(events: _Capture, proxy: FakeServer) -> None:
    proxy.respond_with(403, **{"X-Squid-Error": "ERR_ACCESS_DENIED 0"})
    with pytest.raises(UnsafeUrlError):
        await PublicUrlFetcher().get("http://example.com/x", LIMITS)
    assert _only_denied(events)["route_reason"] == "proxy_denied"
