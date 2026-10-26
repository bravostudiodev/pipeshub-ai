"""`MCPToolProvider` — registers attached, authenticated MCP servers' tools into a
per-request `ToolRegistry`.

Parallel to `PipesHubToolLoader` (`tool_loader.py`) for connector toolsets: one
`register_toolset` group per MCP instance, nested under `lazy_tools_wiring.MCP_PARENT`
("mcp") from the moment it's registered (never top-level `parent=None` — see that
constant's docstring for why).

Discovery-first, no schema-less fallback: the ONLY source of truth is a LIVE
`discovery.discover_tools()` call against the instance (accurate, current schemas). When
`attached_tools` is set (graph selection or chat-time filter), the discovered list is
narrowed to those namespaced names before registration. If discovery times out or the
connection fails, NOTHING is registered for that instance — this used to fall back to the
attached tool list (name/description only) with `input_schema={}`, which is unusable rather
than "callable but unvalidated": the frontend (`sidebar-mcp-utils.ts`) and `_parse_mcp_servers`
(`api/routes/agent.py`) both strip `inputSchema` before persisting an agent's attached tools,
so that fallback tool had NO parameters for the LLM to fill in at all, and every call to it
either omitted required arguments or hallucinated ones the server actually needed — the exact
"incomplete arguments, frequent tool-call failures" symptom this whole module exists to avoid.
An unreachable server disappearing outright, with the failure recorded in
`context.mcp_tool_load_failures` (mirroring `PipesHubToolLoader`'s `toolset_load_failures`) and
surfaced to the model via `capability_summary.py`/`PipesHubGlobalCatalogFallback`, is more
legible than a tool that LOOKS callable and silently fails almost every call. This loader never
hard-blocks the request — the route already did that for missing/unauthenticated instances
before this ever runs (see `api/routes/agent.py`'s "LOAD MCP SERVER CONFIGS" block).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.agent_loop_lib.tools.errors import (
    DuplicateToolNameError,
    DuplicateToolPathError,
)
from app.agents.agent_loop.lazy_tools_wiring import MCP_PARENT
from app.agents.agent_loop.mcp_access import (
    MCPAccessResolver,
    ResolvedMCPServer,
    model_mcp_tool_name,
)
from app.agents.agent_loop.mcp_call_policy import POLICY, Action, Outcome, classify
from app.agents.agent_loop.mcp_session import MCPSessionManager
from app.agents.agent_loop.mcp_tool_adapter import MCPToolAdapter, safe_error_text
from app.agents.mcp.catalog_scope import LegacySharedAuthIneligible
from app.agents.mcp.credential_status import mark_reauth_required
from app.agents.mcp.discovery import build_namespaced_tool_name
from app.agents.mcp.errors import timed_out
from app.agents.mcp.retrieval_trace import discovery_fields, record_event

if TYPE_CHECKING:
    from app.agent_loop_lib.tools.registry import ToolRegistry
    from app.agents.agent_loop.context import AgentContext
    from app.agents.mcp.models import MCPToolInfo

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 30.0

__all__ = ["MCPToolProvider", "DEFAULT_DISCOVERY_TIMEOUT_SECONDS"]


def _mcp_group_name(server: "ResolvedMCPServer") -> str:
    """`mcp_{instance_name}` — an `mcp_`-prefixed group name (same spirit as
    `discovery.build_namespaced_tool_name`'s `mcp_{server_type}_{tool}` tool names) so a
    user-chosen instance name can never collide with an existing connector toolset's group
    name (e.g. an MCP instance named "slack" would otherwise silently replace the native
    Slack toolset's `ToolsetGroup` — see `ToolRegistry.register_toolset`'s "replaces by
    name" semantics)."""
    normalized = server.name.lower().strip().replace(" ", "_").replace("-", "_")
    return f"mcp_{server.group_key or normalized}"


class MCPToolProvider:
    """`load_into(registry, context)` — the MCP analog of `PipesHubToolLoader.load()`."""

    async def load_into(self, registry: "ToolRegistry", context: "AgentContext") -> None:
        resolved_servers = MCPAccessResolver.resolve(context)
        if not resolved_servers:
            return

        state_logger = context.logger or logger
        session_manager = MCPSessionManager(context)

        outcomes = await asyncio.gather(
            *[self._load_one(server, registry, context, session_manager) for server in resolved_servers],
        )
        loaded_count = sum(1 for ok in outcomes if ok)

        if loaded_count:
            registry.register_toolset(
                MCP_PARENT,
                "Attached MCP (Model Context Protocol) servers. Call list_toolsets(toolset) "
                "with one of these names for a one-line description of every tool inside "
                "it, or fetch_tools(toolset) to load the real schemas directly.",
                [],
            )

        state_logger.info(
            "MCPToolProvider: loaded %d/%d attached MCP instance(s) (failures=%s)",
            loaded_count, len(resolved_servers),
            [f.get("instanceId") for f in context.mcp_tool_load_failures],
        )

    async def _load_one(
        self,
        server: "ResolvedMCPServer",
        registry: "ToolRegistry",
        context: "AgentContext",
        session_manager: "MCPSessionManager",
        *,
        timeout_seconds: float | None = None,
    ) -> bool:
        """Registers one instance's tools + group. Returns whether at least one tool was
        registered. Never raises — any discovery/registration failure is recorded on
        `context.mcp_tool_load_failures` and results in `False`."""
        state_logger = context.logger or logger

        discovery_started = asyncio.get_running_loop().time()
        tool_infos, failure_reason = await self._discover_or_fallback(server, timeout_seconds, context, session_manager)
        trace_fields = discovery_fields(server, tool_infos, failure_reason)
        trace_fields["durationMs"] = max(0, round((asyncio.get_running_loop().time() - discovery_started) * 1000))
        await record_event(context, "discovery", trace_fields)
        if not tool_infos:
            context.mcp_tool_load_failures.append({
                "instanceId": server.instance_id, "name": server.name, "reason": failure_reason or "error",
            })
            state_logger.warning(
                "MCPToolProvider: no tools available for MCP instance %s (%s), reason=%s",
                server.instance_id, server.name, failure_reason,
            )
            return False

        registered_names: list[str] = []
        for tool_info in tool_infos:
            adapter = MCPToolAdapter(server, tool_info, session_manager)
            try:
                # Check the full provider schema now, not on a later model
                # turn where one oversized/broken schema could fail the
                # entire gateway request. Never advertise a schema-less tool.
                _ = adapter.raw_input_schema
                registry.register_tool(adapter)
                registered_names.append(adapter.name)
            except (ValueError, RecursionError, TypeError, OverflowError):
                state_logger.warning("MCPToolProvider: skipping invalid schema for tool %s", adapter.name)
            except DuplicateToolNameError:
                # A different type/tool pair may flatten to the same name.
                # Keep both attached instances, but never alias the provider's
                # actual call target or another user's credentials.
                alias = model_mcp_tool_name(server, tool_info.name, force_alias=True)
                if alias == adapter.name:
                    state_logger.warning("MCPToolProvider: duplicate MCP tool alias: %s", alias)
                    continue
                aliased = MCPToolAdapter(
                    server, tool_info.model_copy(update={"namespaced_name": alias}), session_manager,
                )
                try:
                    registry.register_tool(aliased)
                    registered_names.append(alias)
                except (DuplicateToolNameError, DuplicateToolPathError):
                    state_logger.warning("MCPToolProvider: skipping duplicate MCP tool alias: %s", alias)
            except DuplicateToolPathError:
                state_logger.warning("MCPToolProvider: skipping duplicate MCP tool path: %s", adapter.name)

        if not registered_names:
            context.mcp_tool_load_failures.append({
                "instanceId": server.instance_id, "name": server.name, "reason": "error",
                "error": "every discovered tool name collided with an already-registered tool",
            })
            return False

        if server.catalog_instructions and isinstance(server.catalog_instructions, str):
            # Descriptive source guidance only. Never interpolate it into agent
            # instructions or use it to choose identity, grant or tool schema.
            context.tool_state.setdefault("mcp_source_guidance", []).append({
                "instanceId": server.instance_id,
                "displayName": server.display_name,
                "text": server.catalog_instructions[:2000],
            })

        registry.register_toolset(
            _mcp_group_name(server),
            f"{server.display_name} — attached MCP server tools.",
            registered_names,
            parent=MCP_PARENT,
        )
        return True

    async def _discover_or_fallback(
        self, server: "ResolvedMCPServer", timeout_seconds: float | None, context: "AgentContext",
        session_manager: MCPSessionManager,
    ) -> tuple[list[MCPToolInfo] | None, str | None]:
        """Same outcome policy as a tool call (`mcp_call_policy`): an expired OAuth token
        is refreshed once, a rejected credential is recorded so status reads stop saying
        "Connected", anything else is reported as temporarily unavailable."""
        auth_mode = server.instance.get("authMode")
        refreshed = False
        transient_retries = 0
        while True:
            try:
                tool_infos = await session_manager.discover_tools(server, timeout_seconds)
                selected = self._filter_by_attached(server, tool_infos)
                selected = [tool.model_copy(update={
                    "namespaced_name": model_mcp_tool_name(server, tool.name),
                }) for tool in selected]
                return selected, None
            except Exception as exc:
                outcome = classify(exc, auth_mode=auth_mode, last_status=getattr(exc, "status_code", None))
                action = POLICY[outcome].action
                if outcome is Outcome.AUTH_EXPIRED and action is Action.REFRESH and not refreshed:
                    refreshed = True
                    self._log_discovery(server, exc, outcome, action="refresh")
                    try:
                        await session_manager.refresh_credentials(server)
                        continue
                    except Exception as refresh_exc:
                        exc, outcome = refresh_exc, classify(refresh_exc, auth_mode=auth_mode, last_status=None)
                # A deadline already spent the discovery budget; retrying would double the wait.
                if (
                    outcome in (Outcome.TRANSIENT, Outcome.DEAD_SESSION, Outcome.REQUEST_NOT_SENT)
                    and transient_retries < 1 and not timed_out(exc)
                ):
                    transient_retries += 1
                    self._log_discovery(server, exc, outcome, action="retry_listing")
                    await asyncio.sleep(0.5)
                    continue
                self._log_discovery(server, exc, outcome, action="give_up")
                if isinstance(exc, LegacySharedAuthIneligible):
                    return None, "shared_credentials_unsupported"
                if outcome is Outcome.REAUTH_REQUIRED:
                    try:
                        await mark_reauth_required(
                            server.instance_id, server.owner_id, context.config_service,
                            detail=str(exc)[:200], source="discovery",
                            expected_auth=getattr(exc, "rejected_auth", None),
                        )
                    except Exception as mark_exc:
                        logger.warning("MCPToolProvider: could not mark %s as reauth_required: %s", server.instance_id, mark_exc)
                    return None, "reauth_required"
                return None, "discovery_failed"

    @staticmethod
    def _log_discovery(server: "ResolvedMCPServer", exc: BaseException, outcome: Outcome, *, action: str) -> None:
        logger.warning(
            "MCP discovery outcome: instance=%s server=%s outcome=%s action=%s error_type=%s status=%s error=%s",
            server.instance_id, server.name, outcome.value, action, type(exc).__name__,
            getattr(exc, "status_code", None), safe_error_text(exc, server.auth)[:300],
        )

    @staticmethod
    def _attached_full_names(server: "ResolvedMCPServer") -> set[str] | None:
        """Allowed namespaced tool names from the attachment, or None = no restriction."""
        if server.attached_tools is None:
            return None
        server_type = server.instance.get("typeId") or server.name
        allowed: set[str] = set()
        for tool in server.attached_tools:
            full_name = tool.get("fullName")
            if isinstance(full_name, str) and full_name:
                allowed.add(full_name)
            name = tool.get("name")
            if isinstance(name, str) and name:
                allowed.add(build_namespaced_tool_name(server_type, name))
        return allowed

    @classmethod
    def _filter_by_attached(
        cls, server: "ResolvedMCPServer", tool_infos: list[MCPToolInfo],
    ) -> list[MCPToolInfo]:
        allowed = cls._attached_full_names(server)
        if allowed is None:
            return tool_infos
        return [ti for ti in tool_infos if ti.namespaced_name in allowed]
