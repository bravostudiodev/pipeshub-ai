"""Refresh, reconnect and disconnect share storage, not a Python process lock."""
import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.constants.mcp_server_constants import (
    get_mcp_instance_path,
    get_mcp_refresh_lock_path,
)
from app.agents.mcp import credential_lock, oauth_client, token_refresh
from app.agents.mcp.catalog_scope import load_catalog_scope
from app.agents.mcp.credential_lock import credential_refresh_lock
from app.agents.mcp.models import OAuthTokens
from app.agents.mcp.token_refresh import (
    MCPTokenRefreshError,
    MCPTokenRefreshTransientError,
    refresh_credential_record,
)
from app.config.configuration_service import ConfigurationService
from app.config.providers.in_memory_store import InMemoryKeyValueStore
from app.connectors.core.base.token_service.mcp_token_refresh_service import (
    MCPTokenRefreshService,
)
from tests.unit.config.test_conditional_config import make_config

CRED = "/services/mcp/credentials/inst-1/user-1"
CLIENT = "/services/mcp/credentials/inst-1/user-1/dcr-client"


def record(access="old", generation="original") -> dict:
    return {
        "isAuthenticated": True, "credentialGeneration": generation, "connectedAt": 123,
        "oauthTokens": {"accessToken": access, "refreshToken": "refresh", "tokenUrl": "https://example.test/token"},
    }


@pytest.fixture
async def cfg(monkeypatch) -> ConfigurationService:
    monkeypatch.setattr(token_refresh, "_refresh_locks", defaultdict(asyncio.Lock))
    monkeypatch.setattr(token_refresh, "_unsaved_rotations", {})
    monkeypatch.setattr(token_refresh, "_SAVE_RETRY_WAITS_SECONDS", (0.0,) * len(token_refresh._SAVE_RETRY_WAITS_SECONDS))
    monkeypatch.setattr(credential_lock, "CLUSTER_LOCK_POLL_SECONDS", 0.001)
    monkeypatch.setattr(credential_lock, "CLUSTER_LOCK_MAX_POLL_SECONDS", 0.01)
    service = make_config(InMemoryKeyValueStore(MagicMock()))
    await service.set_config(CRED, record())
    await service.set_config(CLIENT, {"clientId": "client", "clientSecret": "secret"})
    return service


def refreshed() -> OAuthTokens:
    return OAuthTokens(access_token="refreshed", refresh_token="rotated", token_url="https://example.test/token")


class IndependentLocalLocks:
    def __getitem__(self, key) -> asyncio.Lock:
        return asyncio.Lock()


@pytest.mark.asyncio
async def test_shared_lease_deduplicates_refresh_with_independent_local_locks(cfg, monkeypatch) -> None:
    monkeypatch.setattr(token_refresh, "_refresh_locks", IndependentLocalLocks())
    other_service = make_config(cfg.store)

    async def rotate(**kwargs) -> OAuthTokens:
        await asyncio.sleep(0.02)
        return refreshed()

    provider = AsyncMock(side_effect=rotate)
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    results = await asyncio.gather(*[
        refresh_credential_record("inst-1", "user-1", service, stale_access_token="old")
        for service in (cfg, other_service, cfg)
    ])
    assert [result.access_token for result in results] == ["refreshed"] * 3
    provider.assert_awaited_once()
    assert await cfg.get_config(get_mcp_refresh_lock_path("inst-1", "user-1")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["disconnect", "reconnect", "deauthenticate"])
async def test_refresh_cannot_overwrite_a_changed_grant(cfg, monkeypatch, action) -> None:
    async def rotate(**kwargs) -> OAuthTokens:
        if action == "disconnect":
            await cfg.delete_config(CRED)
        else:
            current = record("reconnected", "new") if action == "reconnect" else {**record(), "isAuthenticated": False}
            await cfg.set_config(CRED, current)
        return refreshed()

    monkeypatch.setattr(oauth_client, "refresh_access_token", rotate)
    if action == "reconnect":
        result = await refresh_credential_record("inst-1", "user-1", cfg)
        assert result.access_token == "reconnected"
        assert (await cfg.get_config(CRED))["credentialGeneration"] == "new"
    else:
        with pytest.raises(MCPTokenRefreshError):
            await refresh_credential_record("inst-1", "user-1", cfg)
        current = await cfg.get_config(CRED)
        assert current is None if action == "disconnect" else current["isAuthenticated"] is False


@pytest.mark.asyncio
async def test_reconnect_between_read_and_write_is_protected_atomically(cfg, monkeypatch) -> None:
    original = cfg.compare_and_set_config
    changed = False

    async def race(key, expected, value) -> bool:
        nonlocal changed
        if key == CRED and not changed:
            changed = True
            await cfg.set_config(CRED, record("reconnected", "new"))
        return await original(key, expected, value)

    monkeypatch.setattr(cfg, "compare_and_set_config", race)
    monkeypatch.setattr(oauth_client, "refresh_access_token", AsyncMock(return_value=refreshed()))
    result = await refresh_credential_record("inst-1", "user-1", cfg)
    assert result.access_token == "reconnected"
    assert (await cfg.get_config(CRED))["oauthTokens"]["accessToken"] == "reconnected"


@pytest.mark.asyncio
async def test_old_rejection_does_not_report_new_grant_as_rejected(cfg, monkeypatch) -> None:
    async def reject(**kwargs) -> OAuthTokens:
        await cfg.set_config(CRED, record("reconnected", "new"))
        raise oauth_client.MCPRefreshTokenInvalidError("invalid_grant")

    monkeypatch.setattr(oauth_client, "refresh_access_token", reject)
    result = await refresh_credential_record("inst-1", "user-1", cfg)
    assert result.access_token == "reconnected"
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True


@pytest.mark.asyncio
async def test_persistence_retry_does_not_rotate_token_again(cfg, monkeypatch) -> None:
    original = cfg.compare_and_set_config
    writes = 0

    async def save(key, expected, value) -> bool:
        nonlocal writes
        if key == CRED:
            writes += 1
            if writes == 1:
                raise ConnectionError("temporary store outage")
        return await original(key, expected, value)

    provider = AsyncMock(return_value=refreshed())
    monkeypatch.setattr(cfg, "compare_and_set_config", save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    assert (await refresh_credential_record("inst-1", "user-1", cfg)).access_token == "refreshed"
    provider.assert_awaited_once()
    assert writes == 2


@pytest.mark.asyncio
async def test_persistent_save_failure_is_not_success_or_reauth(cfg, monkeypatch) -> None:
    original = cfg.compare_and_set_config

    async def fail_save(key, expected, value) -> bool:
        if key == CRED:
            raise ConnectionError("store unavailable")
        return await original(key, expected, value)

    monkeypatch.setattr(cfg, "compare_and_set_config", fail_save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", AsyncMock(return_value=refreshed()))
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True


@pytest.mark.asyncio
async def test_rotated_tokens_that_could_not_be_saved_are_saved_before_the_next_refresh(cfg, monkeypatch) -> None:
    original = cfg.compare_and_set_config
    store_down = True

    async def flaky_save(key, expected, value) -> bool:
        if key == CRED and store_down:
            raise ConnectionError("store unavailable")
        return await original(key, expected, value)

    used_refresh_tokens: list[str] = []

    async def rotate(**kwargs) -> OAuthTokens:
        used_refresh_tokens.append(kwargs["refresh_token"])
        if kwargs["refresh_token"] == "refresh":
            return refreshed()
        return OAuthTokens(access_token="fresh", refresh_token="rotated-again", token_url="https://example.test/token")

    monkeypatch.setattr(cfg, "compare_and_set_config", flaky_save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", rotate)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)

    store_down = False
    tokens = await refresh_credential_record("inst-1", "user-1", cfg)

    # The dead refresh token is never sent again; the saved rotation is used instead.
    assert used_refresh_tokens == ["refresh", "rotated"]
    assert tokens.access_token == "fresh"
    assert (await cfg.get_config(CRED))["oauthTokens"]["refreshToken"] == "rotated-again"


@pytest.mark.asyncio
async def test_legacy_catalog_migration_does_not_strand_a_parked_rotation(cfg, monkeypatch) -> None:
    legacy = record()
    del legacy["credentialGeneration"]
    await cfg.set_config(CRED, legacy)
    await cfg.set_config(get_mcp_instance_path("inst-1"), {"_id": "inst-1", "orgId": "org", "authMode": "oauth"})
    original_save = cfg.compare_and_set_config
    fail_save = True

    async def flaky_save(path, expected, updated) -> bool:
        if path == CRED and fail_save and expected.get("credentialGeneration"):
            raise ConnectionError("store unavailable after rotation")
        return await original_save(path, expected, updated)

    refresh_tokens: list[str] = []

    async def rotate(**kwargs) -> OAuthTokens:
        refresh_tokens.append(kwargs["refresh_token"])
        if kwargs["refresh_token"] == "refresh":
            return refreshed()
        return OAuthTokens(access_token="fresh", refresh_token="rotated-again", token_url="https://example.test/token")

    monkeypatch.setattr(cfg, "compare_and_set_config", flaky_save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", rotate)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    generation = (await cfg.get_config(CRED))["credentialGeneration"]
    assert generation
    assert token_refresh._unsaved_rotations[("inst-1", "user-1")].credential_generation == generation

    scope = await load_catalog_scope("inst-1", "org", "user-1", cfg)
    assert scope.generation == generation
    fail_save = False
    assert (await refresh_credential_record("inst-1", "user-1", cfg)).access_token == "fresh"
    assert refresh_tokens == ["refresh", "rotated"]


@pytest.mark.asyncio
async def test_legacy_migration_losing_to_reconnect_does_not_refresh_new_grant(cfg, monkeypatch) -> None:
    legacy = record()
    del legacy["credentialGeneration"]
    await cfg.set_config(CRED, legacy)
    original_save = cfg.compare_and_set_config

    async def reconnect_first(path, expected, updated) -> bool:
        if path == CRED:
            await cfg.set_config(CRED, record("old", "new"))
            return False
        return await original_save(path, expected, updated)

    provider = AsyncMock()
    monkeypatch.setattr(cfg, "compare_and_set_config", reconnect_first)
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    tokens = await refresh_credential_record("inst-1", "user-1", cfg)
    assert tokens.access_token == "old"
    assert (await cfg.get_config(CRED))["credentialGeneration"] == "new"
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_generation_write_failure_does_not_exchange_provider_token(cfg, monkeypatch) -> None:
    legacy = record()
    del legacy["credentialGeneration"]
    await cfg.set_config(CRED, legacy)
    original_save = cfg.compare_and_set_config

    async def fail_migration(path, expected, updated) -> bool:
        if path == CRED:
            raise ConnectionError("store unavailable")
        return await original_save(path, expected, updated)

    provider = AsyncMock(return_value=refreshed())
    monkeypatch.setattr(cfg, "compare_and_set_config", fail_migration)
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    provider.assert_not_awaited()
    assert not token_refresh._unsaved_rotations
    assert (await cfg.get_config(CRED)).get("credentialGeneration") is None


@pytest.mark.asyncio
async def test_rotated_token_is_parked_when_lease_read_fails_before_first_save(cfg, monkeypatch) -> None:
    original_assert = credential_lock.RefreshLease.assert_owned
    checks = 0

    async def flaky_assert(lease) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ConnectionError("lease store read unavailable")
        await original_assert(lease)

    used_refresh_tokens: list[str] = []

    async def rotate(**kwargs) -> OAuthTokens:
        used_refresh_tokens.append(kwargs["refresh_token"])
        if kwargs["refresh_token"] == "refresh":
            return refreshed()
        return OAuthTokens(access_token="fresh", refresh_token="rotated-again", token_url="https://example.test/token")

    monkeypatch.setattr(credential_lock.RefreshLease, "assert_owned", flaky_assert)
    monkeypatch.setattr(oauth_client, "refresh_access_token", rotate)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)

    assert (await cfg.get_config(CRED))["oauthTokens"]["refreshToken"] == "refresh"
    assert token_refresh._unsaved_rotations[("inst-1", "user-1")].tokens.refresh_token == "rotated"
    result = await refresh_credential_record("inst-1", "user-1", cfg)
    assert result.refresh_token == "rotated-again"
    assert used_refresh_tokens == ["refresh", "rotated"]
    assert ("inst-1", "user-1") not in token_refresh._unsaved_rotations


@pytest.mark.asyncio
@pytest.mark.parametrize("new_access", ["old", "reconnected"])
async def test_parked_rotation_cannot_overwrite_new_grant_with_same_refresh_token(cfg, monkeypatch, new_access) -> None:
    original = cfg.compare_and_set_config

    async def fail_save(key, expected, value) -> bool:
        if key == CRED:
            raise ConnectionError("store unavailable")
        return await original(key, expected, value)

    provider = AsyncMock(return_value=refreshed())
    monkeypatch.setattr(cfg, "compare_and_set_config", fail_save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    monkeypatch.setattr(cfg, "compare_and_set_config", original)

    reconnect = record(new_access, "new")
    await cfg.set_config(CRED, reconnect)
    result = await refresh_credential_record("inst-1", "user-1", cfg)
    assert result.access_token == new_access
    assert await cfg.get_config(CRED) == reconnect
    assert ("inst-1", "user-1") not in token_refresh._unsaved_rotations
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_parked_rotation_cannot_replace_newer_access_token_with_same_generation(cfg, monkeypatch) -> None:
    original = cfg.compare_and_set_config

    async def fail_save(key, expected, value) -> bool:
        if key == CRED:
            raise ConnectionError("store unavailable")
        return await original(key, expected, value)

    monkeypatch.setattr(cfg, "compare_and_set_config", fail_save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", AsyncMock(return_value=refreshed()))
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    monkeypatch.setattr(cfg, "compare_and_set_config", original)

    newer = record("another-session", "original")
    await cfg.set_config(CRED, newer)
    assert (await refresh_credential_record("inst-1", "user-1", cfg)).access_token == "another-session"
    assert await cfg.get_config(CRED) == newer


@pytest.mark.asyncio
async def test_cancelled_chat_does_not_abandon_rotated_token_save(cfg, monkeypatch) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    async def rotate(**kwargs) -> OAuthTokens:
        started.set()
        await release.wait()
        return refreshed()

    monkeypatch.setattr(oauth_client, "refresh_access_token", rotate)
    task = asyncio.create_task(refresh_credential_record("inst-1", "user-1", cfg))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    for _ in range(100):
        if (await cfg.get_config(CRED))["oauthTokens"]["accessToken"] == "refreshed":
            break
        await asyncio.sleep(0.001)
    assert (await cfg.get_config(CRED))["oauthTokens"]["refreshToken"] == "rotated"


@pytest.mark.asyncio
async def test_expired_lease_holder_cannot_delete_replacement_lease(cfg) -> None:
    path = get_mcp_refresh_lock_path("inst-1", "user-1")
    async with credential_refresh_lock("inst-1", "user-1", cfg):
        cfg.store.store[path].expiry = 1
        assert await cfg.create_config_if_absent(path, {"owner": "replacement"}, ttl_seconds=60)
    assert await cfg.get_config(path) == {"owner": "replacement"}


@pytest.mark.asyncio
async def test_lock_wait_is_bounded_and_temporary(cfg, monkeypatch) -> None:
    await cfg.create_config_if_absent(get_mcp_refresh_lock_path("inst-1", "user-1"), {"owner": "other"}, ttl_seconds=60)
    monkeypatch.setattr(credential_lock, "CLUSTER_LOCK_WAIT_SECONDS", 0)
    provider = AsyncMock()
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    provider.assert_not_awaited()
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True


@pytest.mark.asyncio
async def test_refresh_uses_the_issuing_client_not_the_new_default(cfg, monkeypatch) -> None:
    initial = record()
    initial["oauthTokens"]["clientId"] = "issuing-client"
    await cfg.set_config(CRED, initial)
    await cfg.set_config(CLIENT, {"clientId": "new-client", "previousClient": {"clientId": "issuing-client", "clientSecret": "old-secret"}})
    provider = AsyncMock(return_value=refreshed())
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    await refresh_credential_record("inst-1", "user-1", cfg)
    assert provider.await_args.kwargs["client_id"] == "issuing-client"
    assert provider.await_args.kwargs["client_secret"] == "old-secret"
    assert (await cfg.get_config(CRED))["oauthTokens"]["clientId"] == "issuing-client"


@pytest.mark.asyncio
async def test_unavailable_issuing_client_never_uses_another_clients_secret(cfg, monkeypatch) -> None:
    initial = record()
    initial["oauthTokens"]["clientId"] = "missing-client"
    await cfg.set_config(CRED, initial)
    provider = AsyncMock()
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    with pytest.raises(MCPTokenRefreshError, match="matching OAuth client"):
        await refresh_credential_record("inst-1", "user-1", cfg)
    provider.assert_not_awaited()
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True


@pytest.mark.asyncio
async def test_provider_refresh_has_an_absolute_deadline(cfg, monkeypatch) -> None:
    async def hang(**kwargs) -> OAuthTokens:
        await asyncio.sleep(100)
        raise AssertionError("unreachable")

    monkeypatch.setattr(token_refresh, "REFRESH_REQUEST_MAX_SECONDS", 0.01)
    monkeypatch.setattr(oauth_client, "refresh_access_token", hang)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True
    assert await cfg.get_config(get_mcp_refresh_lock_path("inst-1", "user-1")) is None


@pytest.mark.asyncio
async def test_same_process_lock_wait_is_bounded(cfg, monkeypatch) -> None:
    lock = token_refresh._refresh_locks[("inst-1", "user-1")]
    await lock.acquire()
    monkeypatch.setattr(token_refresh, "LOCAL_LOCK_WAIT_SECONDS", 0.01)
    try:
        with pytest.raises(MCPTokenRefreshTransientError):
            await refresh_credential_record("inst-1", "user-1", cfg)
        assert lock.locked()
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_another_users_grant_is_not_touched(cfg, monkeypatch) -> None:
    other = "/services/mcp/credentials/inst-1/user-2"
    other_record = record("other-users-token", "other-user")
    await cfg.set_config(other, other_record)
    monkeypatch.setattr(oauth_client, "refresh_access_token", AsyncMock(return_value=refreshed()))
    await refresh_credential_record("inst-1", "user-1", cfg)
    assert await cfg.get_config(other) == other_record


@pytest.mark.asyncio
async def test_background_rejection_cannot_deauthenticate_reconnected_user(cfg) -> None:
    service = MCPTokenRefreshService(cfg)
    error = oauth_client.MCPRefreshTokenInvalidError("invalid_grant")
    error.rejected_auth = record()
    await cfg.set_config(CRED, record("reconnected", "new"))
    for _ in range(3):
        await service._handle_refresh_token_invalid(CRED, error)
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True
    assert (await cfg.get_config(CRED))["oauthTokens"]["accessToken"] == "reconnected"


@pytest.mark.asyncio
async def test_background_rejection_counter_resets_for_new_grant(cfg) -> None:
    service = MCPTokenRefreshService(cfg)
    old = oauth_client.MCPRefreshTokenInvalidError("invalid_grant")
    old.rejected_auth = record()
    for _ in range(2):
        await service._handle_refresh_token_invalid(CRED, old)
    new = oauth_client.MCPRefreshTokenInvalidError("invalid_grant")
    new.rejected_auth = record("reconnected", "new")
    await cfg.set_config(CRED, new.rejected_auth)
    await service._handle_refresh_token_invalid(CRED, new)
    assert service._invalid_refresh_failures[CRED] == 1
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True


@pytest.mark.asyncio
async def test_no_expiry_grant_is_not_proactively_refreshed(cfg) -> None:
    token, has_oauth = await MCPTokenRefreshService(cfg)._load_token_from_config(CRED)
    assert token is None
    assert has_oauth is False
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True


@pytest.mark.asyncio
async def test_expired_crashed_holder_lease_can_be_reclaimed(cfg, monkeypatch) -> None:
    path = get_mcp_refresh_lock_path("inst-1", "user-1")
    await cfg.create_config_if_absent(path, {"owner": "crashed-process"}, ttl_seconds=60)
    cfg.store.store[path].expiry = 1
    provider = AsyncMock(return_value=refreshed())
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    assert (await refresh_credential_record("inst-1", "user-1", cfg)).access_token == "refreshed"
    provider.assert_awaited_once()
    assert await cfg.get_config(path) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [True, False])
async def test_lost_lease_cannot_persist_tokens_or_reject_a_grant(cfg, monkeypatch, rejected) -> None:
    path = get_mcp_refresh_lock_path("inst-1", "user-1")

    async def rotate(**kwargs) -> OAuthTokens:
        await cfg.set_config(path, {"owner": "replacement"}, ttl=60)
        if rejected:
            raise oauth_client.MCPRefreshTokenInvalidError("invalid_grant")
        return refreshed()

    monkeypatch.setattr(oauth_client, "refresh_access_token", rotate)
    with pytest.raises(MCPTokenRefreshTransientError):
        await refresh_credential_record("inst-1", "user-1", cfg)
    assert (await cfg.get_config(CRED))["oauthTokens"]["accessToken"] == "old"
    assert (await cfg.get_config(CRED))["isAuthenticated"] is True
    assert await cfg.get_config(path) == {"owner": "replacement"}


@pytest.mark.asyncio
async def test_lost_write_response_reuses_already_persisted_rotated_token(cfg, monkeypatch) -> None:
    original = cfg.compare_and_set_config
    lost_response = False

    async def save(key, expected, value) -> bool:
        nonlocal lost_response
        changed = await original(key, expected, value)
        if key == CRED and not lost_response:
            lost_response = True
            raise ConnectionError("write committed but response was lost")
        return changed

    provider = AsyncMock(return_value=refreshed())
    monkeypatch.setattr(cfg, "compare_and_set_config", save)
    monkeypatch.setattr(oauth_client, "refresh_access_token", provider)
    assert (await refresh_credential_record("inst-1", "user-1", cfg)).access_token == "refreshed"
    provider.assert_awaited_once()
    assert (await cfg.get_config(CRED))["oauthTokens"]["refreshToken"] == "rotated"
