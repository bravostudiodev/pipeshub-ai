"""`WWW-Authenticate` parsing for MCP sign-in and step-up scopes."""
import pytest

from app.agents.mcp.www_authenticate import bearer_challenge, challenge_scopes


@pytest.mark.parametrize("header", [
    'Bearer error="insufficient_scope", scope="read write"',
    'Bearer error="insufficient_scope" scope="read write"',
])
def test_scopes_are_read_with_or_without_commas(header: str) -> None:
    params = bearer_challenge([header])
    assert params["error"] == "insufficient_scope"
    assert challenge_scopes(params) == ["read", "write"]


def test_a_following_challenge_is_not_read_as_a_parameter() -> None:
    assert bearer_challenge(['Basic realm="files" Bearer scope="read"']) == {"scope": "read"}
