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
from mcp.shared.exceptions import MCPError

from app.agents.mcp.errors import (
    MCPConnectionError,
    MCPRequestNotSentError,
    MCPSessionExpiredError,
    MCPUrlBlockedError,
)
from app.agents.mcp.models import MCPAuthMode
from app.agents.mcp.oauth_client import MCPOAuthError, MCPRefreshTokenInvalidError
from app.agents.mcp.token_refresh import (
    MCPTokenRefreshError,
    MCPTokenRefreshTransientError,
)
from app.utils.outbound_http import is_proxy_denial

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
    AUTH_EXPIRED = "auth_expired"        # HTTP 401 on an OAuth instance
    REAUTH_REQUIRED = "reauth_required"  # provider permanently rejected the refresh token
    REFRESH_UNAVAILABLE = "refresh_unavailable"  # missing/incomplete configuration, not rejected credentials
    REQUEST_NOT_SENT = "request_not_sent"
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
    Outcome.REFRESH_UNAVAILABLE: Rule(Action.NONE, ()),
    Outcome.DEAD_SESSION: Rule(Action.REOPEN, (0.0,)),
    Outcome.REQUEST_NOT_SENT: Rule(Action.NONE, (0.5, 1.5)),
    # A transient failure after sending a call does not prove it never ran.
    Outcome.TRANSIENT: Rule(Action.NONE, ()),
    Outcome.REJECTED: Rule(Action.NONE, ()),
    Outcome.UNKNOWN: Rule(Action.NONE, ()),
}

# Caps the sum of sleeps across all retries of one call, so a chat turn can't stall on
# a provider that keeps asking us to wait.
MAX_TOTAL_BACKOFF_SECONDS = 6.0
_RETRY_AFTER_CAP_SECONDS = 5.0


def classify(exc: BaseException, *, auth_mode: str | None, last_status: int | None) -> Outcome:
    # last_status is diagnostic only: it may belong to a listener or another call.
    if isinstance(exc, MCPRefreshTokenInvalidError):
        return Outcome.REAUTH_REQUIRED
    if isinstance(exc, MCPTokenRefreshTransientError):
        return Outcome.TRANSIENT
    if isinstance(exc, MCPTokenRefreshError):
        return Outcome.REFRESH_UNAVAILABLE
    if isinstance(exc, MCPUrlBlockedError):
        return Outcome.REJECTED
    if isinstance(exc, MCPSessionExpiredError):
        return Outcome.DEAD_SESSION
    if isinstance(exc, MCPRequestNotSentError):
        return Outcome.REQUEST_NOT_SENT
    if isinstance(exc, MCPError):
        return Outcome.TOOL_ERROR
    if isinstance(exc, (httpx.TransportError, asyncio.TimeoutError, TimeoutError)):
        return Outcome.TRANSIENT

    status = exc.status_code if isinstance(exc, MCPConnectionError) else None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if is_proxy_denial(status, exc.response.headers):
            return Outcome.REJECTED
    if status is not None:
        if status == 401 and auth_mode == MCPAuthMode.OAUTH.value:
            return Outcome.AUTH_EXPIRED
        if status in (408, 429) or status >= 500:
            return Outcome.TRANSIENT
        if 400 <= status < 500:
            return Outcome.REJECTED

    if isinstance(exc, MCPOAuthError):
        return Outcome.TRANSIENT  # token endpoint unreachable; the credential itself is still good
    if isinstance(exc, MCPConnectionError):
        return Outcome.TRANSIENT
    return Outcome.UNKNOWN


def retry_after_seconds(exc: BaseException) -> float | None:
    """Provider-requested wait, capped so one slow provider can't stall the turn."""
    value = getattr(exc, "retry_after", None)
    if value is None:
        return None
    try:
        return min(float(value), _RETRY_AFTER_CAP_SECONDS)
    except (TypeError, ValueError):
        return None
