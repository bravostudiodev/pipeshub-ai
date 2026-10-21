"""Feature-flagged, content-minimizing MCP retrieval diagnostics."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.featureflag.config.config import CONFIG
from app.services.featureflag.platform_settings import read_platform_feature_flag
from app.utils.request_context import get_context as get_request_context

logger = logging.getLogger(__name__)

TRACE_ROOT = "/services/mcp/retrieval-traces"
TRACE_RETENTION = timedelta(days=7)
TRACE_MAX_RESULTS = 200
TRACE_MAX_COMPARE_RUNS = 10

# Only structural keys useful to compare retrieval behavior cross-provider.
_SAFE_ARGUMENT_KEYS = {
    "channel", "channelid", "channel_id", "channelname", "channel_name",
    "conversation", "conversationid", "conversation_id", "threadid", "thread_id",
    "limit", "count", "cursor", "nextcursor", "next_cursor", "page", "pagesize",
    "page_size", "offset", "sort", "sortby", "sort_by", "order", "direction",
    "from", "to", "start", "end", "after", "before", "since", "until",
    "startdate", "start_date", "enddate", "end_date", "datefrom", "date_from",
    "dateto", "date_to", "operator", "operators", "op",
    "include", "exclude", "types", "type", "scope", "teamid", "team_id",
    "workspaceid", "workspace_id", "user_id", "userid", "thread_ts",
}
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SENSITIVE_KEY_RE = re.compile(r"token|secret|password|authorization|credential|body|content|message|text|query|search|prompt|url|uri", re.I)
_TIME_KEYS = {"ts", "timestamp", "createdat", "created_at", "updatedat", "updated_at", "date", "time"}
_ID_KEYS = {"channelid", "channel_id", "conversationid", "conversation_id", "threadid", "thread_id", "channel", "conversation"}
_SAFE_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "starts_with", "ends_with", "and", "or", "not"}
_SAFE_ENUMS = {
    "sort": {"timestamp", "created_at", "updated_at", "date", "name", "relevance", "score"},
    "sortby": {"timestamp", "created_at", "updated_at", "date", "name", "relevance", "score"},
    "sort_by": {"timestamp", "created_at", "updated_at", "date", "name", "relevance", "score"},
    "order": {"asc", "desc", "ascending", "descending", "newest", "oldest"},
    "direction": {"asc", "desc", "ascending", "descending"},
    "operator": _SAFE_OPERATORS,
    "op": _SAFE_OPERATORS,
    "type": {"message", "file", "page", "document", "issue", "comment", "channel", "user"},
    "types": {"message", "file", "page", "document", "issue", "comment", "channel", "user"},
    "scope": {"public", "private", "all", "workspace", "channel", "direct"},
}
_FILTER_FIELD_NAMES = {
    "channel", "channel_id", "conversation_id", "thread_id", "user_id", "team_id",
    "workspace_id", "created_at", "updated_at", "timestamp", "date", "type", "status",
}
_SECRET_VALUE_RE = re.compile(r"(?i)(bearer\s+|xox[baprs]-|gh[pousr]_|eyJ[A-Za-z0-9_-]{10,}|(?:access|refresh)?_?token=)")
_CHANNEL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def _safe_label(value: Any) -> str | None:  # noqa: ANN401
    if not isinstance(value, str) or not _SAFE_LABEL_RE.fullmatch(value):
        return None
    if _SECRET_VALUE_RE.search(value) or re.search(r"https?://", value, re.I):
        return None
    return value


def _safe_scalar(key: str, value: Any) -> Any:  # noqa: ANN401
    """Return a safe structural scalar or None; never infer safety from key alone."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if abs(value) < 10**15 else None
    if not isinstance(value, str) or len(value) > 256:
        return None
    if re.search(r"https?://|[\r\n]", value, re.I) or _SECRET_VALUE_RE.search(value):
        return None
    normalized = key.lower().replace("-", "_")
    compact = normalized.replace("_", "")
    if normalized in _SAFE_ENUMS or compact in _SAFE_ENUMS:
        enum_key = normalized if normalized in _SAFE_ENUMS else compact
        candidate = value.lower()
        return candidate if candidate in _SAFE_ENUMS[enum_key] else None
    if compact in {"channel", "channelname", "conversation", "conversationname"}:
        return value if _CHANNEL_NAME_RE.fullmatch(value) else None
    if compact in {"cursor", "nextcursor"}:
        # Opaque continuation tokens can be provider-issued credentials. Keep a stable
        # fingerprint so repeated pagination can still be correlated safely.
        return {"fingerprint": hashlib.sha256(value.encode("utf-8")).hexdigest()}
    if compact in {"after", "before", "since", "until", "from", "to", "start", "end", "startdate", "enddate", "datefrom", "dateto", "createdat", "updatedat", "timestamp", "ts", "date", "threadts"}:
        return value if re.fullmatch(r"[0-9TtZz:+. _/-]{1,64}", value) else None
    if compact in {"channelid", "conversationid", "threadid", "teamid", "workspaceid", "userid"}:
        return value if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) else None
    if compact in {"limit", "count", "page", "pagesize", "offset"}:
        return value if value.isdigit() else None
    return None


def _redact_filter(value: Any) -> Any:  # noqa: ANN401
    """Keep only filter structure, allowlisted fields, dates, and known operators."""
    if isinstance(value, list):
        result = [_redact_filter(item) for item in value[:30] if isinstance(item, (dict, list))]
        return [item for item in result if item]
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key, child in value.items():
        norm = str(key).lower().replace("-", "_")
        compact = norm.replace("_", "")
        if not _SAFE_KEY_RE.fullmatch(str(key)) or _SENSITIVE_KEY_RE.search(norm):
            continue
        if compact in {"field", "key", "property", "attribute"}:
            if isinstance(child, str) and child.lower() in _FILTER_FIELD_NAMES:
                result["field"] = child.lower()
        elif norm in {"operator", "op"}:
            safe = _safe_scalar(norm, child)
            if safe is not None:
                result["operator"] = safe
        elif norm in {"filter", "filters"}:
            nested = _redact_filter(child)
            if nested:
                result[norm] = nested
        elif compact in {"after", "before", "since", "until", "from", "to", "start", "end", "date", "createdat", "updatedat", "timestamp"}:
            safe = _safe_scalar(norm, child)
            if safe is not None:
                result[norm] = safe
        elif isinstance(child, (dict, list)):
            nested = _redact_filter(child)
            if nested:
                result[norm] = nested
    return result


def redact_arguments(arguments: Any) -> dict[str, Any]:  # noqa: ANN401
    """Retain allowlisted structural retrieval arguments; omit free text and unknown keys."""
    if not isinstance(arguments, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        normalized = str(key).lower().replace("-", "_")
        compact = normalized.replace("_", "")
        if not _SAFE_KEY_RE.fullmatch(str(key)) or _SENSITIVE_KEY_RE.search(normalized):
            continue
        if normalized not in _SAFE_ARGUMENT_KEYS and compact not in _SAFE_ARGUMENT_KEYS and normalized not in {"filter", "filters"}:
            continue
        if normalized in {"filter", "filters"}:
            nested = _redact_filter(value)
            if nested:
                safe[str(key)] = nested
            continue
        if normalized in {"operators", "operator", "op"} and isinstance(value, list):
            safe_values = [_safe_scalar("operator", item) for item in value[:30]]
            if any(item is not None for item in safe_values):
                safe[str(key)] = [item for item in safe_values if item is not None]
            continue
        safe_value = _safe_scalar(normalized, value)
        if safe_value is not None:
            safe[str(key)] = safe_value
    return safe


def schema_fingerprint(schema: Any) -> str:  # noqa: ANN401
    """Stable SHA-256 of a normalized schema; the schema itself is never persisted."""
    canonical = json.dumps(schema or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _response_metadata(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """Extract only identifiers, timestamps and paging/type hints from a result."""
    rows: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    visited = 0

    def walk(node: Any, parent_key: str = "") -> None:  # noqa: ANN401
        nonlocal visited
        if visited >= 500:
            return
        visited += 1
        structured = getattr(node, "structuredContent", None)
        if structured is not None:
            walk(structured, parent_key)
            return
        text_content = getattr(node, "text", None)
        if isinstance(text_content, str):
            walk(text_content, parent_key)
            return
        if isinstance(node, str):
            # MCP SDKs commonly wrap JSON results in text content blocks. Parse only in
            # memory so metadata can be extracted; arbitrary text is never persisted.
            if len(node) <= 2_000_000:
                try:
                    decoded = json.loads(node)
                except (ValueError, TypeError):
                    return
                if isinstance(decoded, (dict, list)):
                    walk(decoded, parent_key)
            return
        if isinstance(node, dict):
            lowered = {str(k).lower(): v for k, v in node.items()}
            row: dict[str, Any] = {}
            for key, item in lowered.items():
                compact = key.replace("_", "")
                if compact in _ID_KEYS:
                    safe_id = _safe_scalar(key, item)
                    if safe_id is not None:
                        row[key] = safe_id
                if key in _TIME_KEYS:
                    safe_time = _safe_scalar(key, item)
                    if safe_time is not None:
                        row[key] = safe_time
                if key in {"hasmore", "has_more", "hasnextpage", "has_next_page", "nextcursor", "next_cursor"}:
                    metadata["paginated"] = bool(item) if key not in {"nextcursor", "next_cursor"} else bool(item)
                if key in {"truncated", "is_truncated"}:
                    metadata["truncated"] = bool(item)
                if key in {"type", "source", "resulttype", "result_type"}:
                    safe_source = _safe_scalar("type", item)
                    if safe_source is not None:
                        metadata["sourceMetadata"] = safe_source
            if row:
                rows.append(row)
            for key, item in node.items():
                if isinstance(item, (dict, list)):
                    walk(item, str(key))
        elif isinstance(node, list):
            for item in node[:300]:
                walk(item, parent_key)

    walk(value)
    timestamps = [str(row[k]) for row in rows for k in row if k in _TIME_KEYS]
    metadata["resultCount"] = len(rows)
    metadata["returnedIds"] = [
        {k: v for k, v in row.items() if k.replace("_", "") in _ID_KEYS}
        for row in rows[:100] if any(k.replace("_", "") in _ID_KEYS for k in row)
    ]
    if timestamps:
        metadata["oldestTimestamp"] = min(timestamps)
        metadata["newestTimestamp"] = max(timestamps)
    metadata.setdefault("paginated", False)
    metadata.setdefault("truncated", False)
    return metadata


def _safe_error(exc: Exception | None, result: Any = None) -> dict[str, str] | None:  # noqa: ANN401
    if exc is not None:
        return {"class": type(exc).__name__[:100]}
    if isinstance(result, dict):
        code = result.get("code") or result.get("errorCode") or result.get("error_code")
        if isinstance(code, int):
            return {"class": "MCPToolError", "code": str(code)}
        if isinstance(code, str) and len(code) <= 80 and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}", code):
            return {"class": "MCPToolError", "code": code}
    return {"class": "MCPToolError"}


async def trace_enabled(config_service: Any) -> bool:  # noqa: ANN401
    return await read_platform_feature_flag(CONFIG.ENABLE_MCP_RETRIEVAL_TRACE, config_service, default=False)


def trace_identity(context: Any) -> dict[str, Any]:  # noqa: ANN401
    req = get_request_context()
    return {
        "requestId": req.root_id if req else None,
        "runId": context.run_id,
        "conversationId": context.conversation_id,
        "userId": getattr(context, "authenticated_user_id", None) or context.user_id,
        "effectiveUserId": context.user_id,
        "orgId": context.org_id,
    }


async def record_event(context: Any, kind: str, fields: dict[str, Any]) -> None:  # noqa: ANN401
    """Persist one independent event. A failed diagnostic write never affects a chat run."""
    if context is None:
        return
    config_service = context.config_service
    if config_service is None:
        return
    try:
        enabled = context.tool_state.get("_mcp_retrieval_trace_enabled")
        if enabled is None:
            enabled = await trace_enabled(config_service)
            context.tool_state["_mcp_retrieval_trace_enabled"] = enabled
        if not enabled:
            return
        trace_id = context.tool_state.setdefault("_mcp_retrieval_trace_id", str(uuid.uuid4()))
        run_id = context.run_id or trace_id
        identity = {**trace_identity(context), "runId": run_id}
        now = datetime.now(timezone.utc)
        started_at = context.tool_state.setdefault("_mcp_retrieval_trace_started_at", now.timestamp())
        started = datetime.fromtimestamp(started_at, timezone.utc)
        expires_at = started + TRACE_RETENTION
        ttl = max(1, int((expires_at - now).total_seconds()))
        event = {
            "traceId": trace_id,
            "eventId": str(uuid.uuid4()),
            "eventType": kind,
            "recordedAt": now.isoformat(),
            "expiresAt": expires_at.isoformat(),
            **identity,
            **fields,
        }
        index = {
            "traceId": trace_id,
            "runId": run_id,
            "userId": identity["userId"],
            "effectiveUserId": identity["effectiveUserId"],
            "orgId": identity["orgId"],
            "conversationId": identity["conversationId"],
            "startedAt": started.isoformat(),
            "expiresAt": expires_at.isoformat(),
        }
        index_lock = context.tool_state.setdefault("_mcp_retrieval_trace_index_lock", asyncio.Lock())
        async with index_lock:
            if not context.tool_state.get("_mcp_retrieval_trace_indexed"):
                run_key_hash = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
                trace_key_hash = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
                try:
                    by_run = await config_service.set_config(
                        f"{TRACE_ROOT}/{context.org_id}/index/by-run/{run_key_hash}", index, ttl=ttl,
                    )
                    by_trace = await config_service.set_config(
                        f"{TRACE_ROOT}/{context.org_id}/index/by-trace/{trace_key_hash}", index, ttl=ttl,
                    )
                    if by_run and by_trace:
                        context.tool_state["_mcp_retrieval_trace_indexed"] = True
                except Exception:
                    logger.warning("MCP retrieval trace index write failed: trace_id=%s", trace_id, exc_info=True)
        event_key = f"{TRACE_ROOT}/{context.org_id}/events/{trace_id}/{event['eventId']}"
        ok = await config_service.set_config(event_key, event, ttl=ttl)
        if not ok:
            logger.warning("MCP retrieval trace write failed: event_type=%s trace_id=%s", kind, trace_id)
    except Exception:
        logger.warning("MCP retrieval trace recording failed: event_type=%s", kind, exc_info=True)


def discovery_fields(server: Any, tools: list[Any] | None, failure: str | None) -> dict[str, Any]:  # noqa: ANN401
    auth = server.auth if isinstance(server.auth, dict) else {}
    owner = server.owner_id
    has_credential = bool(auth.get("isAuthenticated")) or bool(auth.get("oauthTokens")) or bool(auth.get("apiToken") or auth.get("api_token"))
    tokens = auth.get("oauthTokens") if isinstance(auth.get("oauthTokens"), dict) else {}
    raw_scope = tokens.get("scope")
    scopes = raw_scope.split() if isinstance(raw_scope, str) else []
    expires_at = None
    created_at = tokens.get("createdAt") or tokens.get("created_at")
    expires_in = tokens.get("expiresIn") or tokens.get("expires_in")
    if isinstance(created_at, str) and isinstance(expires_in, (int, float)):
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            expires_at = (created + timedelta(seconds=expires_in)).isoformat()
        except ValueError:
            pass
    return {
        "instanceId": server.instance_id,
        "serverName": _safe_label(server.name),
        "transport": server.instance.get("transport"),
        "authMode": server.instance.get("authMode"),
        "credentialOwnerId": owner,
        "credentialExists": has_credential,
        "credentialScopes": [scope[:100] for scope in scopes[:50] if re.fullmatch(r"[A-Za-z0-9:._-]{1,100}", scope)],
        "credentialExpiresAt": expires_at,
        "outcome": "success" if tools else "failure",
        "errorClass": failure,
        "tools": [
            {"name": _safe_label(tool.namespaced_name), "schemaFingerprint": schema_fingerprint(tool.input_schema)}
            for tool in (tools or [])
            if _safe_label(tool.namespaced_name) is not None
        ],
    }


def invocation_fields(
    server: Any,  # noqa: ANN401
    tool_name: str,
    arguments: dict[str, Any],
    started: float,
    result: Any = None,  # noqa: ANN401
    error: Exception | None = None,
    tool_succeeded: bool | None = None,
) -> dict[str, Any]:
    success = error is None and not bool(getattr(result, "is_error", False))
    if tool_succeeded is not None:
        success = success and tool_succeeded
    data = getattr(result, "data", None)
    if data is None:
        data = getattr(result, "structuredContent", None)
    if data is None:
        data = getattr(result, "content", None)
    if data is None:
        data = result
    return {
        "instanceId": server.instance_id,
        "serverName": _safe_label(server.name),
        "toolName": _safe_label(tool_name),
        "durationMs": max(0, round((time.perf_counter() - started) * 1000)),
        "outcome": "success" if success else "failure",
        "error": _safe_error(error, data) if not success else None,
        "arguments": redact_arguments(arguments),
        "response": _response_metadata(data) if success else {"resultCount": 0, "paginated": False, "truncated": False},
    }
