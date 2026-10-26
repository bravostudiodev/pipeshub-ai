"""`MCPSessionManager` — per-request, per-instance long-lived MCP client cache.

Mirrors `ToolInstanceCreator`'s `_client_cache` (`instance_creator.py`): one open
`MCPClientManager` session per instance is cached on `context.tool_state` so every
`MCPToolAdapter` execution against the same instance within a single chat turn reuses ONE
connection (`MCPClientManager.open()`/`call_tool_in_session()`) instead of reconnecting per
tool call. Phase 1's one-shot discovery (`discovery.discover_tools()`) is unaffected — it
still uses `MCPClientManager.connect()`'s short-lived, per-call contract.

Failure handling lives in `mcp_call_policy`: every raised exception is classified into one
`Outcome`, and `POLICY` says whether to refresh the credential, reopen the session, wait, or
give up. `call` logs exactly one `MCP call outcome:` line per failed attempt, with the same
fields every time, so a log search for that string shows what happened and what was done.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from app.agents.agent_loop.mcp_call_policy import (
    MAX_TOTAL_BACKOFF_SECONDS,
    POLICY,
    Action,
    Outcome,
    Rule,
    classify,
    retry_after_seconds,
)
from app.agents.agent_loop.mcp_tool_adapter import safe_error_text
from app.agents.mcp.catalog_cache import (
    CatalogInvalidated,
    get_for_owner,
    invalidate_scope,
    listing_slot,
)
from app.agents.mcp.catalog_scope import CatalogScopeError, load_catalog_scope
from app.agents.mcp.client import (
    MCPCallInterruptedError,
    MCPClientManager,
    MCPReauthRequiredError,
    discovery_timeout,
)
from app.agents.mcp.credential_status import mark_reauth_required
from app.agents.mcp.discovery import build_auth_env_and_headers, tool_infos_from_listing
from app.agents.mcp.service import (
    credentials_to_discovery_dict,
    instance_config_from_dict,
)
from app.agents.mcp.token_refresh import refresh_credential_record

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext
    from app.agents.agent_loop.mcp_access import ResolvedMCPServer
    from app.agents.mcp.models import MCPToolInfo

logger = logging.getLogger(__name__)

__all__ = ["MCPSessionManager", "refresh_server_credentials"]


async def refresh_server_credentials(
    server: "ResolvedMCPServer", config_service: Any, *, rejected_token: str | None = None,  # noqa: ANN401
) -> None:
    """Refresh the OAuth token behind `server` and update `server.auth` in place so later
    opens this request use it. `rejected_token` is the token the failed request carried; when
    the stored one already differs, another caller refreshed and no provider call is made.
    Raises what `refresh_credential_record` raises."""
    stale_token = rejected_token or credentials_to_discovery_dict(
        server.instance.get("authMode", ""), server.auth,
    ).get("accessToken")
    new_tokens = await refresh_credential_record(
        server.instance_id, server.owner_id, config_service, stale_access_token=stale_token,
    )
    server.auth = {
        **server.auth,
        "isAuthenticated": True,
        "oauthTokens": new_tokens.model_dump(by_alias=True, mode="json"),
    }


def _call_contracts(tools: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    """What a call depends on, by tool name. Descriptions are left out: some providers vary
    them per listing, which would otherwise refuse every call as "tools changed"."""
    return {
        tool["name"]: (tool.get("inputSchema"), tool.get("outputSchema"), tool.get("annotations"))
        for tool in tools
    }


class MCPSessionManager:
    """Cached on `context.tool_state` — construct freely per call site
    (`MCPToolProvider.load_into`, `stream_bridge.py`'s teardown); every
    instance sharing the same `tool_state` dict sees the same underlying
    session cache."""

    def __init__(self, context: "AgentContext") -> None:
        self._context = context
        self._log = context.logger or logger
        state = context.tool_state
        state.setdefault("_mcp_client_managers", {})
        state.setdefault("_mcp_client_locks", {})
        self._managers: dict[str, MCPClientManager] = state["_mcp_client_managers"]
        self._locks: dict[str, asyncio.Lock] = state["_mcp_client_locks"]

    async def discover_tools(
        self, server: "ResolvedMCPServer", timeout_seconds: float | None = None,
    ) -> list[MCPToolInfo]:
        config_service = self._context.config_service
        if config_service is None:
            raise RuntimeError("MCP authority configuration is unavailable")
        self._bind_org(server)
        server.catalog_validated = False
        server.catalog_validated_manager = None
        server.catalog_instructions = None

        async def live(scope: Any) -> Any:  # noqa: ANN401
            server.instance = scope.instance
            server.auth = scope.auth
            server.scope_identity = scope.identity
            manager = await self._get_or_open(server)
            self._sync_headers(manager, server)
            listing = await manager.fetch_tool_listing_in_session()
            if manager.tools_changed:
                await invalidate_scope(scope, config_service)
                raise CatalogInvalidated("MCP tools changed during discovery")
            server.catalog_validated_manager = manager
            return listing

        budget = timeout_seconds if timeout_seconds is not None else discovery_timeout(instance_config_from_dict(server.instance))
        async with asyncio.timeout(budget):
            result = await get_for_owner(
                server.instance_id, server.org_id, server.owner_id, config_service, live,
            )
        server.instance, server.auth = result.scope.instance, result.scope.auth
        server.scope_identity = result.scope.identity
        server.catalog_cache_hit = result.cached
        server.catalog_validated = not result.cached
        if result.cached:
            server.catalog_validated_manager = None
        elif server.catalog_validated_manager is not None and server.catalog_validated_manager.tools_changed:
            await invalidate_scope(result.scope, config_service)
            raise CatalogInvalidated("MCP tools changed during discovery")
        server.catalog_tools = result.tools
        server.catalog_instructions = result.instructions
        server.catalog_validation_lock = server.catalog_validation_lock or asyncio.Lock()
        config = instance_config_from_dict(server.instance)
        return tool_infos_from_listing(result.tools, config)

    async def refresh_credentials(self, server: "ResolvedMCPServer") -> None:
        rejected_token = credentials_to_discovery_dict(server.instance.get("authMode", ""), server.auth).get("accessToken")
        await self._refresh_and_reopen_locked(
            server, stale_manager=self._managers.get(self._cache_key(server)), rejected_token=rejected_token,
        )

    async def call(self, server: "ResolvedMCPServer", tool_name: str, arguments: dict[str, Any]) -> Any:
        self._bind_org(server)
        if self._context.config_service is None:
            raise RuntimeError("MCP authority configuration is unavailable")
        # Discovery recorded the scope this turn's tools came from; the loop re-checks it.
        expected_identity = server.scope_identity or (await load_catalog_scope(
            server.instance_id, server.org_id, server.owner_id, self._context.config_service,
        )).identity
        auth_mode = server.instance.get("authMode")
        attempts: dict[Outcome, int] = {}
        slept = 0.0
        started = time.perf_counter()
        while True:
            manager = None
            pre_execution = True
            rejected_token: str | None = None
            try:
                await self._authorize(server, expected_identity)
                # The token this attempt sends: the check above may have loaded a newer one.
                rejected_token = credentials_to_discovery_dict(auth_mode or "", server.auth).get("accessToken")
                if server.catalog_tools is not None:
                    manager = await self._validate_cached_catalog(server)
                else:
                    manager = await self._get_or_open(server)
                self._sync_headers(manager, server)
                if manager.tools_changed:
                    await self._invalidate_catalog(server)
                    raise CatalogInvalidated("MCP tools changed; this call was not sent. Rediscover tools and replan.")
                await self._authorize(server, expected_identity)
                rejected_token = credentials_to_discovery_dict(auth_mode or "", server.auth).get("accessToken")
                self._sync_headers(manager, server)
                if manager.tools_changed:
                    await self._invalidate_catalog(server)
                    raise CatalogInvalidated("MCP tools changed; this call was not sent")
                pre_execution = False
                return await manager.call_tool_in_session(tool_name, arguments)
            except Exception as exc:
                outcome = classify(exc, auth_mode=auth_mode, last_status=None)
                rule = POLICY[outcome]
                if pre_execution and outcome is Outcome.TRANSIENT:
                    # Opening/listing is safe to retry; never close a healthy sibling's session.
                    rule = Rule(Action.NONE, (0.5,))
                attempt = attempts.get(outcome, 0)
                wait = retry_after_seconds(exc) if outcome is Outcome.TRANSIENT else None
                if wait is None and attempt < rule.max_retries:
                    wait = rule.backoff[attempt]
                can_retry = attempt < rule.max_retries and slept + (wait or 0.0) <= MAX_TOTAL_BACKOFF_SECONDS
                self._log_outcome(server, tool_name, arguments, exc, outcome, attempt, rule.action if can_retry else None)
                if not can_retry:
                    if outcome is Outcome.REAUTH_REQUIRED:
                        raise await self._reauth_error(server, exc, source="tool_call") from exc
                    if not pre_execution and outcome is Outcome.TRANSIENT:
                        raise MCPCallInterruptedError(
                            f"The connection to {server.display_name} was interrupted. This call may have "
                            "completed, so do not repeat it without checking its effect."
                        ) from exc
                    raise
                attempts[outcome] = attempt + 1
                try:
                    if rule.action is Action.REFRESH:
                        await self._refresh_and_reopen_locked(server, stale_manager=manager, rejected_token=rejected_token)
                    elif rule.action is Action.REOPEN and manager is not None:
                        await self._reopen_locked(server, stale_manager=manager)
                except Exception as recovery_exc:
                    recovery_outcome = classify(recovery_exc, auth_mode=auth_mode, last_status=None)
                    self._log_outcome(server, tool_name, arguments, recovery_exc, recovery_outcome, attempt, None)
                    if recovery_outcome is Outcome.REAUTH_REQUIRED:
                        raise await self._reauth_error(server, recovery_exc, source="token_refresh") from recovery_exc
                    raise recovery_exc from exc
                if wait:
                    await asyncio.sleep(wait)
                    slept += wait
                self._log.info(
                    "MCP call retry: instance=%s tool=%s outcome=%s attempt=%d elapsed_ms=%d",
                    server.instance_id, tool_name, outcome.value, attempt + 1,
                    round((time.perf_counter() - started) * 1000),
                )

    async def _reauth_error(
        self, server: "ResolvedMCPServer", exc: BaseException, *, source: str,
    ) -> MCPReauthRequiredError:
        detail = str(exc)[:200]
        try:
            await mark_reauth_required(
                server.instance_id, server.owner_id, self._context.config_service, detail=detail, source=source,
                expected_auth=getattr(exc, "rejected_auth", None),
            )
        except Exception as mark_exc:
            self._log.warning("MCPSessionManager: could not mark %s as reauth_required: %s", server.instance_id, mark_exc)
        return MCPReauthRequiredError(server.display_name, detail)

    def _log_outcome(
        self, server: "ResolvedMCPServer", tool_name: str, arguments: dict[str, Any], exc: BaseException,
        outcome: Outcome, attempt: int, action: Action | None,
    ) -> None:
        emit = self._log.info if action is not None else self._log.warning
        emit(
            "MCP call outcome: instance=%s server=%s tool=%s arg_keys=%s outcome=%s attempt=%d action=%s "
            "error_type=%s status=%s error=%s",
            server.instance_id, server.display_name, tool_name, sorted(arguments or {}), outcome.value, attempt,
            action.value if action else "give_up", type(exc).__name__, getattr(exc, "status_code", None),
            safe_error_text(exc, server.auth)[:300],
        )

    async def aclose_all(self) -> None:
        """Tears down every session opened this request — called from
        `stream_bridge.py`'s existing `finally` block."""
        managers = list(self._managers.values())
        self._managers.clear()
        await asyncio.gather(*(manager.aclose() for manager in managers), return_exceptions=True)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _bind_org(self, server: "ResolvedMCPServer") -> None:
        org_id = self._context.org_id
        if not org_id or (server.org_id and server.org_id != org_id):
            raise CatalogScopeError("MCP caller organization is unavailable")
        server.org_id = org_id

    async def _authorize(self, server: "ResolvedMCPServer", expected_identity: str) -> None:
        scope = await load_catalog_scope(server.instance_id, server.org_id, server.owner_id, self._context.config_service)
        if scope.identity != expected_identity:
            raise CatalogInvalidated("MCP authorization or configuration changed; this call was not sent")
        server.instance, server.auth, server.scope_identity = scope.instance, scope.auth, scope.identity

    @staticmethod
    def _sync_headers(manager: MCPClientManager, server: "ResolvedMCPServer") -> None:
        config = instance_config_from_dict(server.instance)
        _, headers = build_auth_env_and_headers(config, credentials_to_discovery_dict(server.instance.get("authMode", ""), server.auth))
        manager.update_headers(headers)

    def _cache_key(self, server: "ResolvedMCPServer") -> str:
        if not server.scope_identity:
            raise RuntimeError("MCP session has no authoritative generation")
        return f"{server.org_id}:{server.instance_id}:{server.owner_id}:{server.scope_identity}"

    async def _get_or_open(self, server: "ResolvedMCPServer") -> MCPClientManager:
        key = self._cache_key(server)
        manager = self._managers.get(key)
        if manager is not None and manager.is_open:
            return manager
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            manager = self._managers.get(key)
            if manager is not None and manager.is_open:
                return manager
            if manager is not None:
                self._managers.pop(key, None)
                await manager.aclose()
            manager = await self._build_and_open(server)
            self._managers[key] = manager
            return manager

    async def _invalidate_catalog(self, server: "ResolvedMCPServer") -> None:
        scope = await load_catalog_scope(
            server.instance_id, server.org_id, server.owner_id, self._context.config_service,
        )
        await invalidate_scope(scope, self._context.config_service)

    async def _validate_cached_catalog(self, server: "ResolvedMCPServer") -> MCPClientManager:
        if server.catalog_validation_lock is None:
            server.catalog_validation_lock = asyncio.Lock()
        async with server.catalog_validation_lock:
            manager = self._managers.get(self._cache_key(server))
            if manager is not None and manager.is_open and server.catalog_validated and server.catalog_validated_manager is manager and not manager.tools_changed:
                return manager
            async with listing_slot(server.instance_id):
                manager = await self._get_or_open(server)
                self._sync_headers(manager, server)
                listing = await manager.fetch_tool_listing_in_session()
            from app.agents.mcp.catalog_cache import _normalize_listing
            live_tools, _, _ = _normalize_listing(listing)
            if _call_contracts(live_tools) != _call_contracts(server.catalog_tools or []) or manager.tools_changed:
                server.catalog_validated = False
                await self._invalidate_catalog(server)
                raise CatalogInvalidated("MCP tools changed; this call was not sent. Rediscover tools and replan.")
            server.catalog_validated = True
            server.catalog_validated_manager = manager
            return manager

    async def _build_and_open(self, server: "ResolvedMCPServer") -> MCPClientManager:
        config = instance_config_from_dict(server.instance)
        credentials = credentials_to_discovery_dict(server.instance.get("authMode", ""), server.auth)
        env, headers = build_auth_env_and_headers(config, credentials)
        manager = MCPClientManager(config, env=env, headers=headers)
        await manager.open()
        return manager

    async def _refresh_and_reopen_locked(
        self, server: "ResolvedMCPServer", *, stale_manager: MCPClientManager | None, rejected_token: str | None = None,
    ) -> MCPClientManager:
        """Serializes `_refresh_and_reopen` per instance — without this, two concurrent tool
        calls hitting the same expired-token instance would both pop/close the cached
        manager and both rebuild+store a new one, leaking whichever session loses the final
        `self._managers[...] =` write (an orphaned STDIO subprocess or open connection) and
        double-refreshing the credential. `refresh_credential_record` itself is also
        lock-guarded (per instance+owner, shared across every caller of that function — see
        `token_refresh.py`), but that alone doesn't stop two callers here from each rebuilding
        and storing their own session afterward.

        `stale_manager` is the manager identity that triggered this refresh — if another
        task already refreshed-and-reopened while this one was waiting for the lock, the
        session cache entry will have moved on to a different manager object, and this call
        reuses that one instead of refreshing (and reopening) all over again.
        """
        key = self._cache_key(server)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = self._managers.get(key)
            current_token = credentials_to_discovery_dict(server.instance.get("authMode", ""), server.auth).get("accessToken")
            if current_token and current_token != rejected_token:
                # A sibling already refreshed: reuse its token, reopening only a dead session.
                if current is not None and current.is_open:
                    return current
                return await self._reopen_with_current_credentials(server, key, current)
            await self._refresh_and_reopen(server, rejected_token)
            return self._managers[key]

    async def _reopen_with_current_credentials(
        self, server: "ResolvedMCPServer", key: str, stale: MCPClientManager | None,
    ) -> MCPClientManager:
        """Called under the instance lock."""
        if stale is not None:
            self._managers.pop(key, None)
            await stale.aclose()
        self._managers[key] = await self._build_and_open(server)
        return self._managers[key]

    async def _reopen_locked(
        self, server: "ResolvedMCPServer", *, stale_manager: MCPClientManager,
    ) -> MCPClientManager:
        key = self._cache_key(server)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = self._managers.get(key)
            if current is not None and current is not stale_manager:
                return current
            self._managers.pop(key, None)
            await stale_manager.aclose()
            manager = await self._build_and_open(server)
            self._managers[key] = manager
            return manager

    async def _refresh_and_reopen(self, server: "ResolvedMCPServer", rejected_token: str | None = None) -> None:
        await refresh_server_credentials(server, self._context.config_service, rejected_token=rejected_token)
        key = self._cache_key(server)
        current = self._managers.get(key)
        if current is not None and current.is_open:
            config = instance_config_from_dict(server.instance)
            _, headers = build_auth_env_and_headers(config, credentials_to_discovery_dict(server.instance.get("authMode", ""), server.auth))
            current.update_headers(headers)
            return
        old_manager = self._managers.pop(key, None)
        if old_manager is not None:
            await old_manager.aclose()
        self._managers[key] = await self._build_and_open(server)
