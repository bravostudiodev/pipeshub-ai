"""A temporary infrastructure failure must not change a saved user's grant."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.mcp import oauth_client, token_refresh
from app.agents.mcp.credential_status import mark_reauth_required
from app.agents.mcp.token_refresh import (
    MCPTokenRefreshTransientError,
    refresh_credential_record,
)
from app.config.configuration_service import ConfigurationService

CRED_PATH = "/services/mcp/credentials/inst-1/user-1"


@pytest.fixture(autouse=True)
def isolate_record_tests_from_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def lease(*args, **kwargs) -> AsyncIterator[MagicMock]:
        owner = MagicMock()
        owner.assert_owned = AsyncMock()
        yield owner

    monkeypatch.setattr(token_refresh, "credential_refresh_lock", lease)


def _record() -> dict:
    return {
        "isAuthenticated": True, "connectedAt": 123,
        "oauthTokens": {"accessToken": "old", "refreshToken": "refresh", "tokenUrl": "https://example.test/token"},
    }


@pytest.mark.asyncio
async def test_real_config_read_error_is_not_swallowed_as_missing_credential() -> None:
    cfg = object.__new__(ConfigurationService)
    cfg.logger = MagicMock()
    cfg.cache = {}
    cfg.store = MagicMock()
    cfg.store.get_key = AsyncMock(side_effect=ConnectionError("store unavailable"))
    cfg.set_config = AsyncMock()
    with pytest.raises(MCPTokenRefreshTransientError) as raised:
        await refresh_credential_record("inst-1", "user-1", cfg)
    assert isinstance(raised.value.__cause__, ConnectionError)
    cfg.store.get_key.assert_awaited_once_with(CRED_PATH, raise_on_error=True)
    cfg.set_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_client_lookup_does_not_fall_back_to_another_oauth_client() -> None:
    cfg = MagicMock()

    async def read(path, **kwargs) -> dict:
        assert kwargs["raise_on_error"] is True
        if path == CRED_PATH:
            return _record()
        raise TimeoutError("client store unavailable")

    cfg.get_config = AsyncMock(side_effect=read)
    cfg.set_config = AsyncMock()
    with patch.object(oauth_client, "refresh_access_token", AsyncMock()) as refresh:
        with pytest.raises(MCPTokenRefreshTransientError):
            await refresh_credential_record("inst-1", "user-1", cfg)
        refresh.assert_not_awaited()
    assert cfg.get_config.await_count == 2
    cfg.set_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_permanent_rejection_carries_only_the_rejected_snapshot() -> None:
    saved = _record()
    cfg = MagicMock()
    cfg.get_config = AsyncMock(side_effect=lambda path, **kwargs: saved if path == CRED_PATH else {"clientId": "client"})
    cfg.set_config = AsyncMock()
    error = oauth_client.MCPRefreshTokenInvalidError("invalid_grant")
    with patch.object(oauth_client, "refresh_access_token", AsyncMock(side_effect=error)):
        with pytest.raises(oauth_client.MCPRefreshTokenInvalidError) as raised:
            await refresh_credential_record("inst-1", "user-1", cfg)
    assert raised.value.rejected_auth == saved
    saved["oauthTokens"]["accessToken"] = "reconnected"
    assert raised.value.rejected_auth["oauthTokens"]["accessToken"] == "old"
    cfg.set_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_rejection_cannot_mark_newer_reconnected_credential() -> None:
    old = _record()
    current = deepcopy(old)
    current["oauthTokens"]["accessToken"] = "reconnected"
    cfg = MagicMock()
    cfg.get_config = AsyncMock(return_value=current)
    cfg.set_config = AsyncMock(return_value=True)
    assert not await mark_reauth_required(
        "inst-1", "user-1", cfg, detail="rejected", source="discovery", expected_auth=old,
    )
    assert current["isAuthenticated"] is True
    cfg.set_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_matching_rejection_updates_only_the_requested_owner() -> None:
    record = _record()
    cfg = MagicMock()
    cfg.get_config = AsyncMock(return_value=record)
    cfg.compare_and_set_config = AsyncMock(return_value=True)
    assert await mark_reauth_required(
        "inst-1", "user-1", cfg, detail="rejected", source="token_refresh", expected_auth=deepcopy(record),
    )
    assert record["isAuthenticated"] is True
    cfg.get_config.assert_awaited_once_with(CRED_PATH, default=None, use_cache=False, raise_on_error=True)
    path, expected, updated = cfg.compare_and_set_config.await_args.args
    assert expected == record
    assert path == CRED_PATH
    assert updated["isAuthenticated"] is False
    assert updated["connectedAt"] == 123


@pytest.mark.asyncio
async def test_failed_status_write_is_not_reported_as_success_or_mutated_in_memory() -> None:
    record = _record()
    cfg = MagicMock()
    cfg.get_config = AsyncMock(return_value=record)
    cfg.compare_and_set_config = AsyncMock(return_value=False)
    assert not await mark_reauth_required(
        "inst-1", "user-1", cfg, detail="rejected", source="discovery", expected_auth=deepcopy(record),
    )
    assert record["isAuthenticated"] is True
