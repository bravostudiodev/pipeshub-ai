"""MCP egress follows the fork's route policy, with origin checks and direct DNS pinning."""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import httpx2

from app.agents.mcp import wire
from app.agents.mcp.errors import MCPUrlBlockedError
from app.utils.env_utils import env_bool
from app.utils.outbound_http import (
    classify_error,
    emit,
    is_proxy_denial,
    proxy_refusal_status,
)
from app.utils.outbound_proxy import select_route
from app.utils.public_http import UnsafeUrlError, plan_hop
from app.utils.url_fetcher import (
    FetchError,
    PublicTarget,
    UnresolvableHostError,
    check_http_url_without_resolving,
    resolve_public_http_target,
)
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT

if TYPE_CHECKING:
    import ssl
    from collections.abc import Callable


PRIVATE_NETWORK_ENV = "MCP_ALLOW_PRIVATE_NETWORK_URLS"


def private_network_allowed(instance: object = None) -> bool:
    scope = instance.get("scope") if isinstance(instance, dict) else getattr(instance, "scope", None)
    return scope != "personal" and env_bool(PRIVATE_NETWORK_ENV, True)


async def assert_mcp_url_allowed(url: str, *, allow_private: bool) -> PublicTarget:
    try:
        return await asyncio.to_thread(
            resolve_public_http_target, url, block_non_global=not allow_private, allow_private=allow_private,
        )
    except FetchError as exc:
        raise MCPUrlBlockedError("The MCP address is not allowed by the server's network policy.") from exc


async def check_mcp_url(url: str, *, allow_private: bool) -> None:
    try:
        check_http_url_without_resolving(url, block_non_global=not allow_private, allow_private=allow_private)
    except FetchError as exc:
        raise MCPUrlBlockedError("The MCP address is not allowed by the server's network policy.") from exc
    try:
        await assert_mcp_url_allowed(url, allow_private=allow_private)
    except MCPUrlBlockedError as exc:
        # Corporate proxies can resolve approved provider names unavailable to the pod.
        # This is never a fallback from proxy to direct networking.
        if not (isinstance(exc.__cause__, UnresolvableHostError) and select_route(url).uses_proxy):
            raise


def _ssl_context() -> ssl.SSLContext:
    return httpx.create_ssl_context()


def _inner_transport(proxy: str | None) -> httpx2.AsyncBaseTransport:
    context = _ssl_context()
    return httpx2.AsyncHTTPTransport(proxy=proxy, verify=context)


def _origin(url: httpx2.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port or {"http": 80, "https": 443}.get(url.scheme)


class McpGuardedTransport(httpx2.AsyncBaseTransport):
    def __init__(
        self, base_url: str, *, allow_private: bool, inner: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._origin = _origin(httpx2.URL(base_url))
        self._allow_private = allow_private
        self.route = select_route(base_url)
        self._inner = inner or _inner_transport(self.route.proxy_url)
        self._target: PublicTarget | None = None
        self._proxy_checked = False
        self._resolve_lock = asyncio.Lock()

    async def _send(self, request: httpx2.Request) -> httpx2.Response:
        if _origin(request.url) != self._origin:
            raise MCPUrlBlockedError("The MCP server redirected to another origin; credentials were not forwarded.")
        async with self._resolve_lock:
            if self.route.uses_proxy:
                if not self._proxy_checked:
                    await check_mcp_url(self._base_url, allow_private=self._allow_private)
                    self._proxy_checked = True
            elif self._target is None:
                self._target = await assert_mcp_url_allowed(self._base_url, allow_private=self._allow_private)
        if self.route.uses_proxy:
            return await self._inner.handle_async_request(request)
        assert self._target is not None
        last_error: Exception | None = None
        for address in self._target.addresses:
            try:
                plan = plan_hop(str(request.url), replace(self._target, addresses=(address,)))
            except UnsafeUrlError as exc:
                raise MCPUrlBlockedError("The MCP address could not be safely pinned.") from exc
            headers = httpx2.Headers(request.headers)
            headers.update(plan.headers)
            pinned = httpx2.Request(
                request.method, str(plan.request_url), headers=headers, stream=request.stream,
                extensions={**request.extensions, **plan.extensions},
            )
            try:
                return await self._inner.handle_async_request(pinned)
            except (httpx2.ConnectError, httpx2.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpx2.ConnectError("No address could be reached", request=request)

    def _log(self, request: httpx2.Request, started: float, *, status: int | None = None, error: Exception | None = None) -> None:
        outcome = "response" if error is None else classify_error(error)
        if isinstance(error, MCPUrlBlockedError):
            outcome = "denied"
        emit(
            category="mcp", method=request.method, url=str(request.url), via=self.route.via,
            reason=self.route.reason, outcome=outcome, status=status,
            error_type=type(error).__name__ if error else None, duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        started = time.perf_counter()
        try:
            response = await self._send(request)
            if is_proxy_denial(response.status_code, response.headers):
                await response.aclose()
                raise MCPUrlBlockedError(
                    "The outbound proxy refused the MCP request; it was not sent directly.", status_code=response.status_code,
                )
        except httpx2.ProxyError as exc:
            status = proxy_refusal_status(exc)
            failure = MCPUrlBlockedError("The outbound proxy refused the MCP request.", status_code=status) if status else exc
            wire.record_unsent(failure)
            self._log(request, started, status=status, error=failure)
            return httpx2.Response(502, request=request)
        except (MCPUrlBlockedError, httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout,
                httpx2.UnsupportedProtocol) as exc:
            wire.record_unsent(exc)
            self._log(request, started, status=getattr(exc, "status_code", None), error=exc)
            return httpx2.Response(502, request=request)
        except httpx2.TransportError as exc:
            wire.record_lost(exc)
            self._log(request, started, error=exc)
            return httpx2.Response(502, request=request)
        self._log(request, started, status=response.status_code)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def guarded_mcp_http_client(
    base_url: str, *, allow_private: bool, headers: dict[str, str] | None = None,
    auth: httpx2.Auth | None = None, timeout: httpx2.Timeout | None = None,
    read_timeout: float | None = None, inner: httpx2.AsyncBaseTransport | None = None,
) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        timeout=timeout or httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=read_timeout or MCP_DEFAULT_SSE_READ_TIMEOUT),
        headers=headers, auth=auth, trust_env=False,
        transport=McpGuardedTransport(base_url, allow_private=allow_private, inner=inner),
        event_hooks={"response": [wire.record_response]},
    )


def guarded_mcp_http_client_factory(
    base_url: str, *, allow_private: bool, read_timeout: float | None = None,
    inner: httpx2.AsyncBaseTransport | None = None,
) -> Callable[..., httpx2.AsyncClient]:
    def factory(headers=None, timeout=None, auth=None, **kwargs) -> httpx2.AsyncClient:  # noqa: ANN001, ANN003
        return guarded_mcp_http_client(
            base_url, allow_private=allow_private, headers=headers, timeout=timeout, auth=auth,
            read_timeout=read_timeout, inner=inner,
        )
    return factory
