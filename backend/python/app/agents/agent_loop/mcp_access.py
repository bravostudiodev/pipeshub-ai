"""Joins the two MCP fields on `AgentContext` into a flat, runtime-ready list.

`context.mcp_servers` (attached refs — instanceId/name/tools) and
`context.mcp_server_configs` (SENSITIVE: resolved `{"instance": ..., "auth": ...,
"ownerId": ...}` per instanceId) are both already fully resolved by
`api/routes/agent.py`'s chat handler — that route hard-blocks the whole request before it
ever reaches the agent-loop runtime if an attached instance is missing or unauthenticated
(see its "LOAD MCP SERVER CONFIGS" block). `MCPAccessResolver` is intentionally NOT another
etcd round-trip: it only joins the two lists the route already built into one list of
`ResolvedMCPServer` for `MCPToolProvider`/`MCPSessionManager` to act on directly.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext

logger = logging.getLogger(__name__)

__all__ = ["ResolvedMCPServer", "MCPAccessResolver"]


def _normalized_type(name: str) -> str:
    return name.lower().strip().replace(" ", "_").replace("-", "_")


def _instance_namespace_key(instance_id: str) -> str:
    # Never place raw instance IDs in provider tool names: IDs may contain
    # invalid characters or exceed the gateway's function-name limit.
    return "instance_" + hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:16]


_SAFE_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def model_mcp_tool_name(server: "ResolvedMCPServer", raw_name: str, *, force_alias: bool = False) -> str:
    """Model-safe alias only when legacy spelling is ambiguous or invalid.

    The provider still receives its original `raw_name` through MCPToolAdapter;
    no alias can redirect a call to a different instance's credential.
    """
    server_type = server.namespace_key or server.instance.get("typeId") or server.name
    legacy = f"mcp_{_normalized_type(server_type)}_{raw_name}"
    if not force_alias and _SAFE_TOOL_NAME.fullmatch(legacy):
        return legacy
    instance_hash = hashlib.sha256(server.instance_id.encode("utf-8")).hexdigest()[:16]
    tool_hash = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:32]
    return f"mcp_i_{instance_hash}_{tool_hash}"


@dataclass
class ResolvedMCPServer:
    """One attached MCP instance, ready for tool discovery/execution.

    `auth` is mutated in place by `MCPSessionManager` after an on-demand OAuth
    refresh (see that module) so a subsequent call against the SAME
    `ResolvedMCPServer` within this request sees the fresh token without a
    second `MCPAccessResolver.resolve()` pass.
    """

    instance_id: str
    name: str
    display_name: str
    instance: dict[str, Any]  # raw stored instance metadata (transport/url/authMode/...) - no secrets
    auth: dict[str, Any]  # SENSITIVE: resolved credential record ({} for auth_mode "none")
    owner_id: str  # credential_lookup_id (agentKey for service accounts, else the executing user)
    attached_tools: list[dict[str, Any]] | None  # explicit tool selection (graph attachment or chat filter); None = discover everything (unfiltered assistant path)
    org_id: str = ""
    namespace_key: str | None = None
    group_key: str | None = None
    scope_identity: str | None = None
    catalog_cache_hit: bool = False
    catalog_tools: list[dict[str, Any]] | None = None
    catalog_instructions: str | None = None
    catalog_validated: bool = False
    catalog_validated_manager: Any = None
    catalog_validation_lock: Any = None


class MCPAccessResolver:
    """Joins `context.mcp_servers` with `context.mcp_server_configs`."""

    @staticmethod
    def resolve(context: "AgentContext") -> list[ResolvedMCPServer]:
        resolved: list[ResolvedMCPServer] = []
        seen_ids: set[str] = set()
        for mcp_server in context.mcp_servers:
            instance_id = mcp_server.get("instanceId")
            if not instance_id or instance_id in seen_ids:
                continue
            seen_ids.add(instance_id)

            config = context.mcp_server_configs.get(instance_id)
            if not config or not config.get("instance"):
                # The chat route already hard-blocks on a missing/unauthenticated
                # instance for non-assistant agents; reaching this branch just
                # means the instance fell out of `mcp_server_configs` for some
                # other reason it already logged — skip rather than raise,
                # mirroring how `PipesHubToolLoader` skips an unconfigured
                # toolset instead of failing the whole request.
                logger.debug(
                    "MCPAccessResolver: no resolved config for instance %s, skipping", instance_id,
                )
                continue

            resolved.append(ResolvedMCPServer(
                instance_id=instance_id,
                name=mcp_server.get("name") or instance_id,
                display_name=mcp_server.get("displayName") or mcp_server.get("name") or instance_id,
                instance=config["instance"],
                auth=config.get("auth") or {},
                owner_id=config.get("ownerId") or context.user_id,
                org_id=getattr(context, "org_id", ""),
                attached_tools=mcp_server.get("tools"),
            ))
        # Preserve legacy names for the first instance in each group; give
        # later collisions deterministic, ID-derived names. Sorting avoids
        # changing the winner when the attachment/list order changes.
        for key_of, field in (
            (lambda s: _normalized_type(s.instance.get("typeId") or s.name), "namespace_key"),
            (lambda s: _normalized_type(s.name), "group_key"),
        ):
            counts = Counter(key_of(server) for server in resolved)
            reserved = set(counts)  # a hashed alias must not shadow a real type/name
            seen: set[str] = set()
            for server in sorted(resolved, key=lambda s: s.instance_id):
                key = key_of(server)
                # `mcp_foo_bar_baz` can mean type=foo/tool=bar_baz
                # or type=foo_bar/tool=baz. Alias the longer type even
                # when its exact type key is unique in this request.
                prefix_overlap = field == "namespace_key" and any(
                    key.startswith(other + "_") for other in counts if other != key
                )
                if (counts[key] > 1 and key in seen) or prefix_overlap:
                    salt = 0
                    while True:
                        alias = _instance_namespace_key(f"{server.instance_id}:{salt}")
                        if alias not in reserved:
                            reserved.add(alias)
                            setattr(server, field, alias)
                            break
                        salt += 1
                seen.add(key)
        return resolved
