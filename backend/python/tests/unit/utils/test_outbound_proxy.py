"""Proxy selection: one setting, external traffic proxied, in-cluster traffic direct."""

import os

import pytest

from app.utils.outbound_proxy import (
    OutboundProxyConfigError,
    apply_process_environment,
    parse_proxy_url,
    proxy_environment,
    select_route,
)

PROXY = "http://proxy.corp.example:3128"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OUTBOUND_PROXY_URL", "OUTBOUND_PROXY_BYPASS", "CONNECTOR_ENDPOINT", "QDRANT_HOST",
        "REDIS_HOST", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def proxied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", PROXY)


def test_no_setting_means_everything_is_direct() -> None:
    route = select_route("https://api.openai.com/v1/models")
    assert (route.via, route.reason, route.proxy_url) == ("direct", "no_proxy_configured", None)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1/chat/completions",
        "https://mcp.slack.com/mcp",
        "https://accounts.google.com/o/oauth2/token",
        "https://8.8.8.8/dns-query",
        "http://[2606:4700::1]/",
    ],
)
def test_external_destinations_use_the_proxy(proxied: None, url: str) -> None:
    route = select_route(url)
    assert (route.via, route.reason, route.proxy_url) == ("proxy", "external", PROXY)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8088/health",
        "http://127.0.0.1:3000/api",
        "http://[::1]:8000/",
        "http://10.2.3.4:8091/",
        "http://172.20.0.9/",
        "http://192.168.1.10:6333/",
        "http://qdrant:6333/collections",
        "http://connectors.pipeshub.svc:8088/",
        "http://query.ns.svc.cluster.local:8000/",
    ],
)
def test_in_cluster_destinations_stay_direct(proxied: None, url: str) -> None:
    route = select_route(url)
    assert route.via == "direct"
    assert route.reason in ("in_cluster", "configured_bypass")
    assert route.proxy_url is None


def test_configured_service_endpoints_do_not_implicitly_bypass(
    proxied: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONNECTOR_ENDPOINT", "http://connectors.example.org:8088")
    assert select_route("http://connectors.example.org:8088/x").via == "proxy"
    assert select_route("http://other.example.org/x").via == "proxy"


def test_operator_bypass_list(proxied: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_BYPASS", "litellm.corp.example")
    assert select_route("https://litellm.corp.example/v1").via == "direct"
    assert select_route("https://a.mesh.example/").via == "proxy"
    assert select_route("https://mesh.example.evil.com/").via == "proxy"
    assert select_route("http://203.0.113.77/").via == "proxy"
    assert select_route("https://openai.com/").via == "proxy"


def test_suffix_match_does_not_cover_lookalike_hosts(proxied: None) -> None:
    assert select_route("https://evil-svc.com/").via == "proxy"
    assert select_route("https://notinternal.example.com/").via == "proxy"


def test_unparseable_destination_is_never_proxied(proxied: None) -> None:
    assert select_route("not a url").via == "direct"


@pytest.mark.parametrize("value", ["ftp://proxy:21", "proxy.corp.example:3128", "http://", "socks5://p:1080"])
def test_invalid_proxy_setting_fails_loudly(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTBOUND_PROXY_URL", value)
    with pytest.raises(OutboundProxyConfigError):
        select_route("https://example.com/")


def test_blank_setting_is_unset() -> None:
    assert parse_proxy_url("   ") is None


def test_environment_export_matches_the_policy(proxied: None) -> None:
    env = proxy_environment()
    assert env["HTTPS_PROXY"] == env["https_proxy"] == env["HTTP_PROXY"] == PROXY
    no_proxy = env["NO_PROXY"].split(",")
    assert {"localhost", ".svc", ".cluster.local", "127.0.0.0/8", "10.0.0.0/8"} <= set(no_proxy)


def test_apply_replaces_inherited_variables(proxied: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # apply_process_environment writes os.environ directly; keep it from leaking into other tests.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("HTTPS_PROXY", "http://stale:1")
    monkeypatch.setenv("ALL_PROXY", "http://stale:2")
    assert apply_process_environment() is True
    assert os.environ["HTTPS_PROXY"] == PROXY
    assert "ALL_PROXY" not in os.environ


def test_apply_without_setting_leaves_environment_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://inherited:1")
    assert apply_process_environment() is False
    assert os.environ["HTTPS_PROXY"] == "http://inherited:1"
