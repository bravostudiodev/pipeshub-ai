"""Single place that says how an MCP tool call can fail and what to do about each case.

`MCPSessionManager.call` classifies every raised exception with `classify`, looks the
outcome up in `POLICY`, and either retries (with the listed action) or gives up. Adding a
new failure mode means adding an enum member and a table row, not a new branch.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

import httpx
from fastmcp.exceptions import ToolError

from app.agents.mcp.client import MCPConnectionError, MCPProviderRejectedError
from app.agents.mcp.models import MCPAuthMode
from app.agents.mcp.oauth_client import MCPOAuthError, MCPRefreshTokenInvalidError
from app.agents.mcp.token_refresh import MCPTokenRefreshError

__all__ = [
    "MAX_TOTAL_BACKOFF_SECONDS",
    "POLICY",
    "Action",
    "Outcome",
    "Rule",
    "classify",
    "retry_after_seconds",
]


class Outcome(str, Enum):
    TOOL_ERROR = "tool_error"            # server ran the tool and reported a failure (bad arguments etc.)
    AUTH_EXPIRED = "auth_expired"        # 401 or expiry-looking message on an OAuth instance
    REAUTH_REQUIRED = "reauth_required"  # credentials can't be refreshed; the user must reconnect
    DEAD_SESSION = "dead_session"        # client closed by an earlier failure this turn
    TRANSIENT = "transient"              # network, timeout, 429, 5xx
    REJECTED = "rejected"                # other 4xx: retrying the same call can't succeed
    UNKNOWN = "unknown"


class Action(str, Enum):
    NONE = "none"
    REOPEN = "reopen"
    REFRESH = "refresh"


@dataclass(frozen=True)
class Rule:
    action: Action
    backoff: tuple[float, ...]  # one entry per retry; empty means give up at once

    @property
    def max_retries(self) -> int:
        return len(self.backoff)


POLICY: dict[Outcome, Rule] = {
    Outcome.TOOL_ERROR: Rule(Action.NONE, ()),
    Outcome.AUTH_EXPIRED: Rule(Action.REFRESH, (0.0,)),
    Outcome.REAUTH_REQUIRED: Rule(Action.NONE, ()),
    Outcome.DEAD_SESSION: Rule(Action.REOPEN, (0.0,)),
    Outcome.TRANSIENT: Rule(Action.REOPEN, (0.5, 1.5)),
    Outcome.REJECTED: Rule(Action.NONE, ()),
    Outcome.UNKNOWN: Rule(Action.NONE, ()),
}

# Caps the sum of sleeps across all retries of one call, so a chat turn can't stall on
# a provider that keeps asking us to wait.
MAX_TOTAL_BACKOFF_SECONDS = 6.0
_RETRY_AFTER_CAP_SECONDS = 5.0

# MCP SDKs surface token expiry as a 401 or a JSON-RPC error with one of these in the
# message, not as a typed exception.
_EXPIRY_MARKERS = ("401", "unauthorized", "invalid_token", "invalid token", "token expired", "expired")


def classify(exc: BaseException, *, auth_mode: str | None, last_status: int | None) -> Outcome:
    if isinstance(exc, (MCPRefreshTokenInvalidError, MCPTokenRefreshError)):
        return Outcome.REAUTH_REQUIRED
    if isinstance(exc, ToolError):
        return Outcome.TOOL_ERROR
    if isinstance(exc, RuntimeError) and "not connected" in str(exc).lower():
        return Outcome.DEAD_SESSION
    if isinstance(exc, (httpx.TransportError, asyncio.TimeoutError, TimeoutError)):
        return Outcome.TRANSIENT

    status = exc.status_code if isinstance(exc, MCPProviderRejectedError) else None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    if status is None and isinstance(exc, MCPConnectionError):
        status = last_status
    if status is not None:
        if status == 401 or (status == 403 and auth_mode == MCPAuthMode.OAUTH.value):
            return _auth_outcome(auth_mode)
        if status == 429 or status >= 500:
            return Outcome.TRANSIENT
        if 400 <= status < 500:
            return Outcome.REJECTED

    if isinstance(exc, MCPOAuthError):
        return Outcome.TRANSIENT  # token endpoint unreachable; the credential itself is still good
    if any(marker in str(exc).lower() for marker in _EXPIRY_MARKERS):
        return _auth_outcome(auth_mode)
    if isinstance(exc, MCPConnectionError):
        return Outcome.TRANSIENT
    return Outcome.UNKNOWN


def _auth_outcome(auth_mode: str | None) -> Outcome:
    # Only OAuth credentials can be refreshed without the user; anything else needs a reconnect.
    return Outcome.AUTH_EXPIRED if auth_mode == MCPAuthMode.OAUTH.value else Outcome.REAUTH_REQUIRED


def retry_after_seconds(exc: BaseException) -> float | None:
    """Provider-requested wait, capped so one slow provider can't stall the turn."""
    value = getattr(exc, "retry_after", None)
    if value is None:
        return None
    try:
        return min(float(value), _RETRY_AFTER_CAP_SECONDS)
    except (TypeError, ValueError):
        return None
