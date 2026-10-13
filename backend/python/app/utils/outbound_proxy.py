"""Outbound HTTP proxy settings and per-destination route selection.

One application setting, ``OUTBOUND_PROXY_URL``, names the forward proxy for external
HTTP(S) traffic. ``select_route`` is the single place that decides, for a destination URL,
whether a request goes through that proxy or directly. In-cluster traffic (loopback,
private addresses, ``.svc``/``.cluster.local`` names and single-label service names)
stays direct. ``OUTBOUND_PROXY_BYPASS`` names explicit internal hosts such as a model gateway.

``apply_process_environment`` exports the same decision as ``HTTP(S)_PROXY``/``NO_PROXY``
so SDKs that honor the standard variables (httpx, requests, botocore, urllib, httplib2)
follow it; clients that do not (aiohttp, curl, the SSRF-guarded URL fetcher) are
configured explicitly from ``select_route``.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

OUTBOUND_PROXY_URL_ENV = "OUTBOUND_PROXY_URL"
OUTBOUND_PROXY_BYPASS_ENV = "OUTBOUND_PROXY_BYPASS"

_PROXY_SCHEMES = ("http", "https")
_LOCAL_SUFFIXES = (".localhost", ".svc", ".cluster.local")
_PRIVATE_NETWORKS = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)

Via = Literal["proxy", "direct"]
Reason = Literal["external", "in_cluster", "configured_bypass", "no_proxy_configured"]


class OutboundProxyConfigError(ValueError):
    """``OUTBOUND_PROXY_URL`` is set but unusable. Fails startup rather than silently going direct."""


@dataclass(frozen=True)
class OutboundRoute:
    via: Via
    reason: Reason
    proxy_url: str | None = None

    @property
    def uses_proxy(self) -> bool:
        return self.via == "proxy"


def _normalize_host(host: str) -> str:
    return host.strip().lower().strip("[]").removesuffix(".")


def host_of(value: str) -> str | None:
    """Hostname of a URL, ``host[:port]`` or bare host; None when there is none."""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value if "//" in value else f"//{value}")
        host = parsed.hostname
    except ValueError:
        return None
    return _normalize_host(host) if host else None


def parse_proxy_url(raw: str | None) -> str | None:
    """The validated proxy URL, or None when unset.

    Raises:
        OutboundProxyConfigError: for a value that is not an ``http(s)://host[:port]`` URL.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        host, _ = parsed.hostname, parsed.port
    except ValueError as e:
        raise OutboundProxyConfigError(f"{OUTBOUND_PROXY_URL_ENV} is not a valid URL") from e
    if parsed.scheme not in _PROXY_SCHEMES or not host:
        raise OutboundProxyConfigError(
            f"{OUTBOUND_PROXY_URL_ENV} must be an http:// or https:// URL with a host"
        )
    return raw


def _bypass() -> frozenset[str]:
    hosts = {"localhost"}
    for raw in os.environ.get(OUTBOUND_PROXY_BYPASS_ENV, "").split(","):
        entry = raw.strip()
        if not entry:
            continue
        host = host_of(entry)
        if not host or "*" in entry or "/" in entry or entry.startswith("."):
            raise OutboundProxyConfigError(
                f"{OUTBOUND_PROXY_BYPASS_ENV} accepts exact hostnames only"
            )
        hosts.add(host)
    return frozenset(hosts)


def _in_cluster_reason(host: str, bypass: frozenset[str]) -> Reason | None:
    if host in bypass:
        return "configured_bypass"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if any(ip in ipaddress.ip_network(net) for net in _PRIVATE_NETWORKS):
            return "in_cluster"
        return None
    if host.endswith(_LOCAL_SUFFIXES):
        return "in_cluster"
    # A dotless name only resolves inside a private network (Compose/Kubernetes service name).
    if "." not in host:
        return "in_cluster"
    return None


def select_route(url: str) -> OutboundRoute:
    """Decide whether a request to ``url`` goes through the outbound proxy.

    Raises:
        OutboundProxyConfigError: when ``OUTBOUND_PROXY_URL`` is set but invalid.
    """
    proxy_url = parse_proxy_url(os.environ.get(OUTBOUND_PROXY_URL_ENV))
    if proxy_url is None:
        return OutboundRoute("direct", "no_proxy_configured")
    host = host_of(url)
    if host is None:
        # Nothing to judge: never send an unparseable destination through the proxy unchecked.
        return OutboundRoute("direct", "in_cluster")
    reason = _in_cluster_reason(host, _bypass())
    if reason is not None:
        return OutboundRoute("direct", reason)
    return OutboundRoute("proxy", "external", proxy_url)


def proxy_environment() -> dict[str, str]:
    """``HTTP(S)_PROXY``/``NO_PROXY`` equivalents of the setting; empty when no proxy is set."""
    proxy_url = parse_proxy_url(os.environ.get(OUTBOUND_PROXY_URL_ENV))
    if proxy_url is None:
        return {}
    bypass = _bypass()
    # IPv4 CIDR ranges are understood by requests, curl and botocore; IPv6 ranges break
    # httpx's parser, so only the loopback address is exported for IPv6.
    no_proxy = [*sorted(bypass), "::1", *_LOCAL_SUFFIXES, *_PRIVATE_NETWORKS[:5]]
    joined = ",".join(no_proxy)
    return {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
        "NO_PROXY": joined,
        "no_proxy": joined,
    }


def apply_process_environment() -> bool:
    """Export the setting as the standard proxy variables, replacing any inherited ones so
    the single setting is authoritative. Returns whether a proxy is configured."""
    env = proxy_environment()
    if not env:
        return False
    for stale in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(stale, None)
    os.environ.update(env)
    return True
