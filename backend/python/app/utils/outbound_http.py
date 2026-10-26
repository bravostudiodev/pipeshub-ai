"""Structured logging and proxy routing for every outbound HTTP request.

``install_outbound_http`` runs once per service. It exports the proxy setting
(``app.utils.outbound_proxy``) and instruments httpx, aiohttp, requests, curl_cffi and
urllib at the library level, so requests made by SDKs the app does not construct itself
(OpenAI, Anthropic and similar HTTP clients) are routed and logged like the app's own.

Each request, including every redirect hop of httpx/requests, emits one
``outbound_http {json}`` line with the destination host and port, method, whether it went
through the proxy or directly, the client category and the outcome. Paths, query strings,
headers, cookies and bodies are never recorded; the request id is the existing trace id.
"""

# Library monkeypatches wrap arbitrary third-party call signatures, hence the untyped wrappers.
# ruff: noqa: ANN401, FBT001, PLW0603

from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from app.utils.logger import create_logger
from app.utils.outbound_proxy import (
    OUTBOUND_PROXY_URL_ENV,
    OutboundProxyConfigError,
    OutboundRoute,
    apply_process_environment,
    host_of,
    parse_proxy_url,
    select_route,
)
from app.utils.request_context import NO_CONTEXT, current_display_id

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

logger = create_logger("outbound_http")

_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}
_MAX_HOST_LEN = 255

_category_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "outbound_category", default=None
)


@contextmanager
def outbound_category(name: str) -> Iterator[None]:
    """Label clients created, and requests sent, inside the block."""
    token = _category_var.set(name)
    try:
        yield
    finally:
        _category_var.reset(token)


def destination(url: str) -> tuple[str, int | None]:
    """Hostname and port of ``url``; the path, query and userinfo are dropped on purpose."""
    try:
        parts = urlsplit(url)
        host = (host_of(url) or "unknown")[:_MAX_HOST_LEN]
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:
        return "unparseable", None
    return host, port


def classify_error(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if "proxy" in name:
        return "proxy_error"
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "timeout"
    if "ssl" in name or "certificate" in name:
        return "tls_error"
    if "connect" in name or isinstance(exc, ConnectionError):
        return "connect_error"
    return "error"


def emit(
    *,
    category: str,
    method: str,
    url: str,
    via: str,
    reason: str,
    outcome: str,
    status: int | None = None,
    error_type: str | None = None,
    duration_ms: float | None = None,
    proxy: str | None = None,
    level: int | None = None,
) -> None:
    host, port = destination(url)
    request_id = current_display_id()
    fields: dict[str, Any] = {
        "dest_host": host,
        "dest_port": port,
        "method": (method or "").upper()[:16],
        "via": via,
        "route_reason": reason,
        "category": category,
        "outcome": outcome,
        "status": status,
        "error_type": error_type,
        "duration_ms": None if duration_ms is None else round(duration_ms, 1),
        "proxy": proxy,
        "request_id": None if request_id == NO_CONTEXT else request_id,
    }
    payload = {k: v for k, v in fields.items() if v is not None}
    if level is None:
        level = logging.INFO if outcome == "response" else logging.WARNING
    logger.log(level, "outbound_http %s", json.dumps(payload, separators=(",", ":")))


def _squid_error(headers: "Mapping[str, str]") -> str:
    return next((v for k, v in headers.items() if k.lower() == "x-squid-error"), "")


def is_proxy_generated(headers: "Mapping[str, str]") -> bool:
    """Whether the proxy wrote this response itself (any Squid error page), so it says
    nothing about what the origin would have answered."""
    return bool(_squid_error(headers))


def is_proxy_denial(status: int, headers: "Mapping[str, str]") -> bool:
    """Whether the proxy itself, not the origin, refused a request: 407, or a Squid
    access-control error page."""
    return status == 407 or "ACCESS_DENIED" in _squid_error(headers).upper()


def proxy_refusal_status(exc: BaseException) -> int | None:
    """CONNECT policy status; unrelated transport failures have no status."""
    message = str(exc)
    match = (
        re.match(r"^(40[37])\b", message)
        or re.search(r"Tunnel connection failed:\s*(40[37])\b", message, re.IGNORECASE)
    )
    return int(match.group(1)) if match else None


def log_denied(url: str, reason: str, *, method: str = "GET", category: str | None = None) -> None:
    """A request the SSRF policy refused before any connection was made."""
    if category is None:
        category = _category_var.get() or "http"
    emit(
        category=category,
        method=method,
        url=url,
        via="none",
        reason=reason,
        outcome="denied",
        level=logging.WARNING,
    )


def _proxy_label(proxy_url: str | None) -> str | None:
    """``host:port`` of the proxy: its credentials never reach a log line."""
    if not proxy_url:
        return None
    host, port = destination(proxy_url)
    return f"{host}:{port}" if port else host


def _safe_route(url: str) -> OutboundRoute:
    try:
        return select_route(url)
    except OutboundProxyConfigError:
        return OutboundRoute("direct", "no_proxy_configured")


def _proxy_configured() -> bool:
    return bool(os.environ.get(OUTBOUND_PROXY_URL_ENV, "").strip())


def _configured_proxy() -> str | None:
    try:
        return parse_proxy_url(os.environ.get(OUTBOUND_PROXY_URL_ENV))
    except OutboundProxyConfigError:
        return None


def _reason_for(policy: OutboundRoute, actual_via: str) -> str:
    # A destination the policy sends through the proxy but the client connected to directly
    # is a leak around the proxy; make it stand out.
    if policy.uses_proxy and actual_via == "direct":
        return "proxy_not_applied"
    if actual_via == "proxy" and not policy.uses_proxy:
        return "proxy_forced_by_client"
    return policy.reason


def _report(
    *,
    category: str,
    method: str,
    url: str,
    actual_via: str,
    proxy_url: str | None,
    started: float,
    status: int | None = None,
    exc: BaseException | None = None,
) -> None:
    policy = _safe_route(url)
    reason = _reason_for(policy, actual_via)
    leak = reason == "proxy_not_applied"
    if exc is not None:
        outcome, error_type, level = classify_error(exc), type(exc).__name__, logging.WARNING
        if actual_via == "proxy" and outcome == "connect_error":
            outcome = "proxy_error"
        if actual_via == "proxy":
            status = proxy_refusal_status(exc) or status
    else:
        outcome, error_type = "response", None
        level = logging.WARNING if leak else logging.INFO
    emit(
        category=category,
        method=method,
        url=url,
        via=actual_via,
        reason=reason,
        outcome=outcome,
        status=status,
        error_type=error_type,
        duration_ms=(time.perf_counter() - started) * 1000,
        proxy=_proxy_label(proxy_url) if actual_via == "proxy" else None,
        level=level,
    )


# ---------------------------------------------------------------- httpx

def tag_client(client: object, category: str) -> None:
    """Pin the category of an httpx/aiohttp client created by code that knows what it is for."""
    client._outbound_category = category  # type: ignore[attr-defined]


def _httpx_route(client: Any, request: Any) -> tuple[str, str | None]:
    """Whether httpx will send ``request`` through a proxy, read from the transport it
    picked rather than recomputed from policy."""
    try:
        transport = client._transport_for_url(request.url)
    except Exception:
        return "direct", None
    pool = getattr(transport, "_pool", None)
    if pool is None or "proxy" not in type(pool).__name__.lower():
        return "direct", None
    proxy = getattr(pool, "_proxy_url", None)
    label = None
    if proxy is not None:
        host = proxy.host.decode("ascii", "replace")
        label = f"{proxy.scheme.decode('ascii', 'replace')}://{host}:{proxy.port}" if proxy.port else None
    return "proxy", label


def _patch_httpx() -> None:
    import httpx

    def wrap_init(cls: type) -> None:
        original = cls.__init__

        @functools.wraps(original)
        def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
            original(self, *args, **kwargs)
            if not hasattr(self, "_outbound_category"):
                self._outbound_category = _category_var.get() or "http"
            # Only clients that took their proxy from the environment are re-routed below;
            # a proxy a caller passed explicitly is theirs to decide.
            self._outbound_env_proxy = bool(kwargs.get("trust_env", True)) and not any(
                kwargs.get(name) for name in ("proxy", "proxies", "mounts", "transport")
            )

        cls.__init__ = __init__  # type: ignore[method-assign]

        original_transport_for_url = cls._transport_for_url

        @functools.wraps(original_transport_for_url)
        def _transport_for_url(self: Any, url: Any) -> Any:
            transport = original_transport_for_url(self, url)
            # NO_PROXY cannot name dotless service names or CIDR ranges in httpx, so the
            # route policy has the last word on what stays direct.
            if (
                transport is not self._transport
                and getattr(self, "_outbound_env_proxy", False)
                and not _safe_route(str(url)).uses_proxy
                and _proxy_configured()
            ):
                return self._transport
            return transport

        cls._transport_for_url = _transport_for_url  # type: ignore[method-assign]

    def wrap_send(cls: type, is_async: bool) -> None:
        original = cls._send_single_request

        def info(self: Any, request: Any) -> tuple[str, str, str | None, str, float]:
            via, proxy = _httpx_route(self, request)
            return (
                getattr(self, "_outbound_category", None) or "http",
                via,
                proxy,
                str(request.url),
                time.perf_counter(),
            )

        def nested_aiohttp(self: Any, request: Any) -> bool:
            """LiteLLM's httpx transport delegates the request to aiohttp, which logs it."""
            try:
                transport = self._transport_for_url(request.url)
            except Exception:
                return False
            return type(transport).__name__ == "LiteLLMAiohttpTransport"

        if is_async:

            @functools.wraps(original)
            async def _send_single_request(self: Any, request: Any) -> Any:
                if nested_aiohttp(self, request):
                    return await original(self, request)
                category, via, proxy, url, started = info(self, request)
                try:
                    response = await original(self, request)
                except Exception as exc:
                    _report(category=category, method=request.method, url=url,
                            actual_via=via, proxy_url=proxy, started=started, exc=exc)
                    raise
                _report(category=category, method=request.method, url=url,
                        actual_via=via, proxy_url=proxy, started=started, status=response.status_code)
                return response
        else:

            @functools.wraps(original)
            def _send_single_request(self: Any, request: Any) -> Any:  # type: ignore[misc]
                if nested_aiohttp(self, request):
                    return original(self, request)
                category, via, proxy, url, started = info(self, request)
                try:
                    response = original(self, request)
                except Exception as exc:
                    _report(category=category, method=request.method, url=url,
                            actual_via=via, proxy_url=proxy, started=started, exc=exc)
                    raise
                _report(category=category, method=request.method, url=url,
                        actual_via=via, proxy_url=proxy, started=started, status=response.status_code)
                return response

        cls._send_single_request = _send_single_request  # type: ignore[method-assign]

    for cls, is_async in ((httpx.AsyncClient, True), (httpx.Client, False)):
        wrap_init(cls)
        wrap_send(cls, is_async)


# ---------------------------------------------------------------- aiohttp

def _patch_aiohttp() -> None:
    import aiohttp

    original_init = aiohttp.ClientSession.__init__
    original_request = aiohttp.ClientSession._request

    def _hop_logger() -> aiohttp.TraceConfig:
        trace = aiohttp.TraceConfig()

        async def on_redirect(session: Any, ctx: Any, params: Any) -> None:
            state = ctx.trace_request_ctx
            if not isinstance(state, dict) or "category" not in state:
                return
            _report(
                category=state["category"], method=params.method,
                url=str(params.url), actual_via=state["via"], proxy_url=state["proxy"],
                started=state["started"], status=params.response.status,
            )
            state["started"] = time.perf_counter()

        trace.on_request_redirect.append(on_redirect)
        return trace

    @functools.wraps(original_init)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        traces = list(kwargs.get("trace_configs") or [])
        traces.append(_hop_logger())
        kwargs["trace_configs"] = traces
        if _proxy_configured():
            # Routing is decided per request in ``_request``; aiohttp's own environment
            # lookup would send in-cluster names through the proxy.
            kwargs["trust_env"] = False
        original_init(self, *args, **kwargs)
        if not hasattr(self, "_outbound_category"):
            self._outbound_category = _category_var.get() or "http"

    @functools.wraps(original_request)
    async def _request(self: Any, method: str, str_or_url: Any, **kwargs: Any) -> Any:
        url = str(str_or_url)
        explicit_proxy = kwargs.get("proxy")
        policy = _safe_route(url)
        proxy_url: str | None = None
        if explicit_proxy is not None:
            proxy_url = str(explicit_proxy)
        elif policy.uses_proxy and policy.proxy_url:
            # aiohttp ignores the standard variables unless the session opted in, and
            # takes proxy credentials as a separate argument rather than from the URL.
            proxy_url, auth = _split_proxy_credentials(policy.proxy_url)
            kwargs["proxy"] = proxy_url
            if auth is not None and kwargs.get("proxy_auth") is None:
                _add_proxy_credentials(kwargs, url, auth)
        state = {
            "category": getattr(self, "_outbound_category", None) or "http",
            "via": "proxy" if proxy_url else "direct",
            "proxy": proxy_url,
            "started": time.perf_counter(),
        }
        kwargs["trace_request_ctx"] = state if kwargs.get("trace_request_ctx") is None else kwargs["trace_request_ctx"]
        try:
            response = await original_request(self, method, str_or_url, **kwargs)
        except Exception as exc:
            _report(category=state["category"], method=method, url=url,
                    actual_via=state["via"], proxy_url=proxy_url, started=state["started"], exc=exc)
            raise
        _report(category=state["category"], method=method, url=str(response.url),
                actual_via=state["via"], proxy_url=proxy_url, started=state["started"], status=response.status)
        return response

    aiohttp.ClientSession.__init__ = __init__  # type: ignore[method-assign]
    aiohttp.ClientSession._request = _request  # type: ignore[method-assign]


def _add_proxy_credentials(kwargs: dict[str, Any], url: str, auth: tuple[str, str]) -> None:
    """Send proxy credentials without aiohttp's deprecated ``proxy_auth``: a CONNECT tunnel
    (https) takes them from ``proxy_headers``, a plain-HTTP forward request from its own headers."""
    import aiohttp

    value = aiohttp.encode_basic_auth(*auth)
    if urlsplit(url).scheme in ("https", "wss"):
        kwargs["proxy_headers"] = {**dict(kwargs.get("proxy_headers") or {}), "Proxy-Authorization": value}
    else:
        kwargs["headers"] = {**dict(kwargs.get("headers") or {}), "Proxy-Authorization": value}


def _split_proxy_credentials(proxy_url: str) -> tuple[str, tuple[str, str] | None]:
    from urllib.parse import unquote

    parts = urlsplit(proxy_url)
    if not parts.username:
        return proxy_url, None
    host = parts.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    if parts.port:
        netloc += f":{parts.port}"
    stripped = parts._replace(netloc=netloc).geturl()
    return stripped, (unquote(parts.username), unquote(parts.password or ""))


# ---------------------------------------------------------------- requests

def _patch_requests() -> None:
    import requests
    from requests.utils import select_proxy

    original_send = requests.Session.send

    @functools.wraps(original_send)
    def send(self: Any, request: Any, **kwargs: Any) -> Any:
        url = request.url or ""
        proxies = kwargs.get("proxies") or {}
        proxy_url = select_proxy(url, proxies)
        policy = _safe_route(url)
        if not proxy_url and policy.uses_proxy and policy.proxy_url:
            proxy_url = policy.proxy_url
            kwargs["proxies"] = {**proxies, "http": proxy_url, "https": proxy_url}
        elif proxy_url and not policy.uses_proxy and _proxy_configured() and proxy_url == _configured_proxy():
            # The environment proxy was picked for a destination the policy keeps direct.
            kwargs["proxies"] = {k: v for k, v in proxies.items() if v != proxy_url}
            proxy_url = None
        category = _category_var.get() or "http"
        via = "proxy" if proxy_url else "direct"
        started = time.perf_counter()
        try:
            response = original_send(self, request, **kwargs)
        except Exception as exc:
            _report(category=category, method=request.method or "", url=url,
                    actual_via=via, proxy_url=proxy_url, started=started, exc=exc)
            raise
        # requests calls Session.send again for redirects; those inner calls log their
        # own status. The outer call represents the original hop, not the final hop.
        first = response.history[0] if response.history else response
        _report(category=category, method=request.method or "", url=url,
                actual_via=via, proxy_url=proxy_url, started=started, status=first.status_code)
        return response

    requests.Session.send = send  # type: ignore[method-assign]


# ---------------------------------------------------------------- curl_cffi

def _patch_curl_cffi() -> None:
    from curl_cffi import requests as curl_requests

    def wrap(cls: type, is_async: bool) -> None:
        original = cls.request

        def prepare(self: Any, url: str) -> tuple[str, str, str | None, float]:
            category = _category_var.get() or "http"
            policy = _safe_route(url)
            via = "proxy" if policy.uses_proxy else "direct"
            return category, via, policy.proxy_url, time.perf_counter()

        def explicit_proxy(self: Any, kwargs: dict[str, Any], url: str) -> None:
            # A pinned session sets CURLOPT_PROXY itself; anything the caller chose stands.
            if kwargs.get("proxy") or kwargs.get("proxies") or getattr(self, "proxies", None):
                return
            if "PROXY" in {getattr(k, "name", str(k)) for k in getattr(self, "curl_options", {})}:
                return
            policy = _safe_route(url)
            if policy.uses_proxy:
                kwargs["proxy"] = policy.proxy_url

        if is_async:

            @functools.wraps(original)
            async def request(self: Any, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
                explicit_proxy(self, kwargs, url)
                category, via, proxy, started = prepare(self, url)
                try:
                    response = await original(self, method, url, *args, **kwargs)
                except Exception as exc:
                    _report(category=category, method=method, url=url, actual_via=via,
                            proxy_url=proxy, started=started, exc=exc)
                    raise
                _report(category=category, method=method, url=url, actual_via=via,
                        proxy_url=proxy, started=started, status=response.status_code)
                return response
        else:

            @functools.wraps(original)
            def request(self: Any, method: str, url: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
                explicit_proxy(self, kwargs, url)
                category, via, proxy, started = prepare(self, url)
                try:
                    response = original(self, method, url, *args, **kwargs)
                except Exception as exc:
                    _report(category=category, method=method, url=url, actual_via=via,
                            proxy_url=proxy, started=started, exc=exc)
                    raise
                _report(category=category, method=method, url=url, actual_via=via,
                        proxy_url=proxy, started=started, status=response.status_code)
                return response

        cls.request = request  # type: ignore[method-assign]

    wrap(curl_requests.Session, False)
    wrap(curl_requests.AsyncSession, True)


# ---------------------------------------------------------------- urllib

def _patch_urllib() -> None:
    original_open = urllib.request.OpenerDirector.open
    original_proxy_open = urllib.request.ProxyHandler.proxy_open

    @functools.wraps(original_proxy_open)
    def proxy_open(self: Any, req: Any, proxy: str, type: str) -> Any:
        # urllib does not consistently honor CIDR or dotless names in NO_PROXY.
        if not _safe_route(req.full_url).uses_proxy and _proxy_configured():
            return None
        return original_proxy_open(self, req, proxy, type)

    urllib.request.ProxyHandler.proxy_open = proxy_open  # type: ignore[method-assign]

    @functools.wraps(original_open)
    def open_(self: Any, fullurl: Any, *args: Any, **kwargs: Any) -> Any:
        url = fullurl if isinstance(fullurl, str) else getattr(fullurl, "full_url", "")
        method = "GET" if isinstance(fullurl, str) else (fullurl.get_method() if hasattr(fullurl, "get_method") else "GET")
        category = _category_var.get() or "http"
        # The default opener reads the standard proxy variables; proxy_open above
        # keeps cluster destinations direct when urllib ignores NO_PROXY.
        policy = _safe_route(url)
        via = "proxy" if policy.uses_proxy else "direct"
        started = time.perf_counter()
        try:
            response = original_open(self, fullurl, *args, **kwargs)
        except urllib.error.HTTPError as exc:
            _report(category=category, method=method, url=url, actual_via=via,
                    proxy_url=policy.proxy_url, started=started, status=exc.code)
            raise
        except Exception as exc:
            _report(category=category, method=method, url=url, actual_via=via,
                    proxy_url=policy.proxy_url, started=started, exc=exc)
            raise
        _report(category=category, method=method, url=url, actual_via=via,
                proxy_url=policy.proxy_url, started=started, status=getattr(response, "status", None))
        return response

    urllib.request.OpenerDirector.open = open_  # type: ignore[method-assign]


# ---------------------------------------------------------------- install

_installed = False


def install_outbound_http() -> None:
    """Route and log outbound HTTP for this process. Idempotent.

    Raises:
        OutboundProxyConfigError: when ``OUTBOUND_PROXY_URL`` is set but invalid, so a
            typo stops the service instead of sending external traffic around the proxy.
    """
    global _installed
    if _installed:
        return
    configured = apply_process_environment()
    for patch in (_patch_httpx, _patch_aiohttp, _patch_requests, _patch_curl_cffi, _patch_urllib):
        try:
            patch()
        except ImportError:
            logger.debug("Outbound instrumentation skipped: %s not installed", patch.__name__)
    _installed = True
    if configured:
        route = select_route("https://external.invalid/")
        logger.info(
            "Outbound HTTP proxy enabled: %s (in-cluster destinations connect directly)",
            _proxy_label(route.proxy_url),
        )
    else:
        logger.info("Outbound HTTP proxy not configured: all outbound HTTP connects directly")
