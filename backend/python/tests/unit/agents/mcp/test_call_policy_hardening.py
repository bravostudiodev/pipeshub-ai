"""Authentication decisions must not depend on diagnostic prose or listener status."""
import httpx
import pytest

from app.agents.agent_loop.mcp_call_policy import POLICY, Action, Outcome, classify
from app.agents.mcp.client import MCPConnectionError, MCPProviderRejectedError
from app.agents.mcp.oauth_client import MCPRefreshTokenInvalidError
from app.agents.mcp.token_refresh import MCPTokenRefreshError


@pytest.mark.parametrize("auth_mode", ["oauth", "api_token", "headers", "none"])
@pytest.mark.parametrize("message", [
    "Timed out discovering tools for instance source-401 after 30s",
    "The session expired", "unauthorized field in request",
])
def test_diagnostic_text_cannot_reject_credentials(auth_mode: str, message: str) -> None:
    assert classify(RuntimeError(message), auth_mode=auth_mode, last_status=401) is Outcome.UNKNOWN


@pytest.mark.parametrize("status", [401, 403, 404, 405])
def test_unrelated_listener_status_does_not_classify_connection_failure(status: int) -> None:
    assert classify(MCPConnectionError("connection reset"), auth_mode="oauth", last_status=status) is Outcome.TRANSIENT


def test_opening_failure_uses_its_own_http_status() -> None:
    assert classify(MCPConnectionError("refused", status_code=401), auth_mode="oauth", last_status=405) is Outcome.AUTH_EXPIRED


@pytest.mark.parametrize("auth_mode", ["oauth", "api_token", "headers"])
def test_permission_denial_is_not_expired_auth(auth_mode: str) -> None:
    error = MCPProviderRejectedError(403, "https://example.test/mcp", "insufficient_scope", None)
    assert classify(error, auth_mode=auth_mode, last_status=None) is Outcome.REJECTED


def test_non_oauth_401_does_not_invalidate_saved_credentials() -> None:
    error = MCPProviderRejectedError(401, "https://example.test/mcp", None, None)
    assert classify(error, auth_mode="api_token", last_status=None) is Outcome.REJECTED


def test_refresh_configuration_failure_is_not_permanent_rejection() -> None:
    outcome = classify(MCPTokenRefreshError("No credential record found"), auth_mode="oauth", last_status=None)
    assert outcome is not Outcome.REAUTH_REQUIRED
    assert POLICY[outcome].action is Action.NONE


def test_permanent_refresh_rejection_still_requires_reconnect() -> None:
    assert classify(MCPRefreshTokenInvalidError("invalid_grant"), auth_mode="oauth", last_status=None) is Outcome.REAUTH_REQUIRED


@pytest.mark.parametrize("error", [
    TimeoutError("no answer"), httpx.ReadError("connection reset"),
    MCPProviderRejectedError(408, "https://example.test/mcp", None, None),
    MCPProviderRejectedError(503, "https://example.test/mcp", None, None),
    MCPProviderRejectedError(429, "https://example.test/mcp", None, "2"),
])
def test_ambiguous_execution_is_not_automatically_replayed(error: Exception) -> None:
    outcome = classify(error, auth_mode="oauth", last_status=None)
    assert outcome is Outcome.TRANSIENT
    assert POLICY[outcome].max_retries == 0
