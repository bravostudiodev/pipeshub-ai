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
    classify,
    retry_after_seconds,
)
from app.agents.mcp.client import MCPClientManager, MCPReauthRequiredError
from app.agents.mcp.credential_status import mark_reauth_required
from app.agents.mcp.discovery import build_auth_env_and_headers
from app.agents.mcp.service import (
    credentials_to_discovery_dict,
    instance_config_from_dict,
)
from app.agents.mcp.token_refresh import refresh_credential_record

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext
    from app.agents.agent_loop.mcp_access import ResolvedMCPServer

logger = logging.getLogger(__name__)

__all__ = ["MCPSessionManager", "refresh_server_credentials"]


async def refresh_server_credentials(server: "ResolvedMCPServer", config_service: Any) -> None:
    """Refresh the OAuth token behind `server` and update `server.auth` in place so later
    opens this request use it. Raises what `refresh_credential_record` raises."""
    new_tokens = await refresh_credential_record(server.instance_id, server.owner_id, config_service)
    server.auth = {
        "isAuthenticated": True,
        "oauthTokens": new_tokens.model_dump(by_alias=True, mode="json"),
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

    async def call(self, server: "ResolvedMCPServer", tool_name: str, arguments: dict[str, Any]) -> Any:
        auth_mode = server.instance.get("authMode")
        attempts: dict[Outcome, int] = {}
        slept = 0.0
        started = time.perf_counter()
        while True:
            manager = await self._get_or_open(server)
            try:
                return await manager.call_tool_in_session(tool_name, arguments)
            except Exception as exc:
                last_http = manager.last_http
                outcome = classify(
                    exc, auth_mode=auth_mode,
                    last_status=last_http.status_code if last_http else None,
                )
                rule = POLICY[outcome]
                attempt = attempts.get(outcome, 0)
                wait = retry_after_seconds(exc) if outcome is Outcome.TRANSIENT else None
                if wait is None and attempt < rule.max_retries:
                    wait = rule.backoff[attempt]
                can_retry = attempt < rule.max_retries and slept + (wait or 0.0) <= MAX_TOTAL_BACKOFF_SECONDS
                self._log_outcome(server, tool_name, arguments, exc, outcome, attempt, rule.action if can_retry else None, last_http)
                if not can_retry:
                    if outcome is Outcome.REAUTH_REQUIRED:
                        raise await self._reauth_error(server, exc, source="tool_call") from exc
                    raise
                attempts[outcome] = attempt + 1
                try:
                    if rule.action is Action.REFRESH:
                        await self._refresh_and_reopen_locked(server, stale_manager=manager)
                    elif rule.action is Action.REOPEN:
                        await self._reopen_locked(server, stale_manager=manager)
                except Exception as recovery_exc:
                    recovery_outcome = classify(recovery_exc, auth_mode=auth_mode, last_status=None)
                    self._log_outcome(server, tool_name, arguments, recovery_exc, recovery_outcome, attempt, None, None)
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
            )
        except Exception as mark_exc:
            self._log.warning("MCPSessionManager: could not mark %s as reauth_required: %s", server.instance_id, mark_exc)
        return MCPReauthRequiredError(server.display_name, detail)

    def _log_outcome(
        self, server: "ResolvedMCPServer", tool_name: str, arguments: dict[str, Any], exc: BaseException,
        outcome: Outcome, attempt: int, action: Action | None, last_http: Any,
    ) -> None:
        emit = self._log.info if action is not None else self._log.warning
        emit(
            "MCP call outcome: instance=%s server=%s tool=%s arg_keys=%s outcome=%s attempt=%d action=%s "
            "error_type=%s error=%s last_http=%s %s body=%s request=%s",
            server.instance_id, server.display_name, tool_name, sorted(arguments or {}), outcome.value, attempt,
            action.value if action else "give_up", type(exc).__name__, str(exc)[:300],
            getattr(last_http, "status_code", None), getattr(last_http, "url", None),
            getattr(last_http, "error_body", None), getattr(last_http, "error_request", None),
        )

    async def aclose_all(self) -> None:
        """Tears down every session opened this request — called from
        `stream_bridge.py`'s existing `finally` block."""
        for instance_id, manager in list(self._managers.items()):
            try:
                await manager.aclose()
            except Exception as exc:
                self._log.debug("MCPSessionManager: error closing session for %s: %s", instance_id, exc)
        self._managers.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_or_open(self, server: "ResolvedMCPServer") -> MCPClientManager:
        manager = self._managers.get(server.instance_id)
        if manager is not None:
            return manager
        lock = self._locks.setdefault(server.instance_id, asyncio.Lock())
        async with lock:
            manager = self._managers.get(server.instance_id)
            if manager is not None:
                return manager
            manager = await self._build_and_open(server)
            self._managers[server.instance_id] = manager
            return manager

    async def _build_and_open(self, server: "ResolvedMCPServer") -> MCPClientManager:
        config = instance_config_from_dict(server.instance)
        credentials = credentials_to_discovery_dict(server.instance.get("authMode", ""), server.auth)
        env, headers = build_auth_env_and_headers(config, credentials)
        manager = MCPClientManager(config, env=env, headers=headers)
        await manager.open()
        return manager

    async def _refresh_and_reopen_locked(
        self, server: "ResolvedMCPServer", *, stale_manager: MCPClientManager,
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
        lock = self._locks.setdefault(server.instance_id, asyncio.Lock())
        async with lock:
            current = self._managers.get(server.instance_id)
            if current is not None and current is not stale_manager:
                return current
            await self._refresh_and_reopen(server)
            return self._managers[server.instance_id]

    async def _reopen_locked(
        self, server: "ResolvedMCPServer", *, stale_manager: MCPClientManager,
    ) -> MCPClientManager:
        lock = self._locks.setdefault(server.instance_id, asyncio.Lock())
        async with lock:
            current = self._managers.get(server.instance_id)
            if current is not None and current is not stale_manager:
                return current
            self._managers.pop(server.instance_id, None)
            await stale_manager.aclose()
            manager = await self._build_and_open(server)
            self._managers[server.instance_id] = manager
            return manager

    async def _refresh_and_reopen(self, server: "ResolvedMCPServer") -> None:
        old_manager = self._managers.pop(server.instance_id, None)
        if old_manager is not None:
            await old_manager.aclose()

        await refresh_server_credentials(server, self._context.config_service)
        manager = await self._build_and_open(server)
        self._managers[server.instance_id] = manager
