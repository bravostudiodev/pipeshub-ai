import asyncio
import copy

import pytest

from app.agents.constants.mcp_server_constants import (
    get_mcp_credentials_path,
    get_mcp_instance_path,
)
from app.agents.mcp.catalog_scope import (
    CatalogScopeError,
    LegacySharedAuthIneligible,
    load_catalog_scope,
    scope_is_current,
)


class Store:
    def __init__(self, instance=None, auth=None) -> None:
        self.data = {
            get_mcp_instance_path("i"): instance
            if instance is not None
            else {"_id": "i", "orgId": "o", "authMode": "oauth"},
            get_mcp_credentials_path("i", "u"): auth
            if auth is not None
            else {"isAuthenticated": True, "oauthTokens": {"accessToken": "secret"}},
        }
        self.calls = []
        self.cas_race = None
        self.fail = False

    async def get_config(self, path, **kwargs) -> object:
        self.calls.append((path, kwargs))
        assert kwargs == {"default": None, "use_cache": False, "raise_on_error": True}
        if self.fail:
            raise RuntimeError("store unavailable")
        return copy.deepcopy(self.data.get(path))

    async def create_config_if_absent(self, path, value, **kwargs) -> bool:
        if path in self.data:
            return False
        self.data[path] = copy.deepcopy(value)
        return True

    async def compare_and_set_config(self, path, expected, updated) -> bool:
        if self.cas_race is not None:
            self.data[path] = self.cas_race
            self.cas_race = None
            return False
        if self.data.get(path) != expected:
            return False
        if updated is None:
            self.data.pop(path, None)
        else:
            self.data[path] = copy.deepcopy(updated)
        return True


@pytest.mark.asyncio
async def test_strict_reads_and_legacy_generation_cas() -> None:
    s = Store()
    scope = await load_catalog_scope("i", "o", "u", s)
    assert len(s.calls) >= 2  # Legacy generation assignment also rechecks under the refresh lease.
    assert all(call[1]["use_cache"] is False for call in s.calls)
    assert (
        s.data[get_mcp_credentials_path("i", "u")]["credentialGeneration"]
        == scope.generation
    )


@pytest.mark.asyncio
async def test_org_owner_and_instance_are_bound() -> None:
    s = Store()
    a = await load_catalog_scope("i", "o", "u", s)
    with pytest.raises(CatalogScopeError):
        await load_catalog_scope("i", "other", "u", s)
    with pytest.raises(CatalogScopeError):
        await load_catalog_scope("missing", "o", "u", s)
    with pytest.raises(CatalogScopeError):
        await load_catalog_scope("i", "o", "", s)
    s.data[get_mcp_credentials_path("i", "v")] = {
        "isAuthenticated": True,
        "credentialGeneration": "g",
        "oauthTokens": {"accessToken": "other-user-token"},
    }
    b = await load_catalog_scope("i", "o", "v", s)
    assert a.identity != b.identity


@pytest.mark.asyncio
async def test_missing_disconnected_and_reauth_rejected() -> None:
    missing = Store()
    del missing.data[get_mcp_credentials_path("i", "u")]
    cases = [
        missing,
        Store(auth={"isAuthenticated": False}),
        Store(auth={"isAuthenticated": False, "deauthReason": "credential_rejected"}),
    ]
    for s in cases:
        with pytest.raises(CatalogScopeError):
            await load_catalog_scope("i", "o", "u", s)


@pytest.mark.asyncio
async def test_read_failure_propagates_and_is_not_current_false() -> None:
    s = Store()
    scope = await load_catalog_scope("i", "o", "u", s)
    s.fail = True
    with pytest.raises(RuntimeError):
        await scope_is_current(scope, s)


@pytest.mark.asyncio
async def test_cas_lost_to_disconnect_is_rejected() -> None:
    s = Store(auth={"isAuthenticated": True})
    s.cas_race = {"isAuthenticated": False}
    with pytest.raises(CatalogScopeError):
        await load_catalog_scope("i", "o", "u", s)


@pytest.mark.asyncio
async def test_generation_configuration_scopes_invalidate_but_token_rotation_does_not() -> (
    None
):
    s = Store(
        auth={
            "isAuthenticated": True,
            "credentialGeneration": "g",
            "oauthTokens": {"accessToken": "a", "refreshToken": "r", "scope": "read"},
        }
    )
    a = await load_catalog_scope("i", "o", "u", s)
    s.data[get_mcp_credentials_path("i", "u")]["accessToken"] = "rotated"
    assert (await load_catalog_scope("i", "o", "u", s)).identity == a.identity
    s.data[get_mcp_credentials_path("i", "u")]["oauthTokens"]["scope"] = "write"
    assert (await load_catalog_scope("i", "o", "u", s)).identity != a.identity


@pytest.mark.asyncio
async def test_instance_configuration_and_generation_invalidate() -> None:
    s = Store(auth={"isAuthenticated": True, "credentialGeneration": "g", "oauthTokens": {"accessToken": "token"}})
    a = await load_catalog_scope("i", "o", "u", s)
    s.data[get_mcp_instance_path("i")]["url"] = "https://new.invalid"
    b = await load_catalog_scope("i", "o", "u", s)
    assert a.identity != b.identity
    s.data[get_mcp_credentials_path("i", "u")]["credentialGeneration"] = "new"
    assert b.identity != (await load_catalog_scope("i", "o", "u", s)).identity


@pytest.mark.asyncio
async def test_none_auth_is_owner_private_and_shared_legacy_not_read() -> None:
    s = Store(instance={"_id": "i", "orgId": "o", "authMode": "none"})
    a = await load_catalog_scope("i", "o", "u", s)
    b = await load_catalog_scope("i", "o", "v", s)
    assert a.auth == {} and a.identity != b.identity
    legacy = Store(
        instance={
            "_id": "i",
            "orgId": "o",
            "authMode": "api_token",
            "useAdminAuth": True,
        }
    )
    with pytest.raises(LegacySharedAuthIneligible):
        await load_catalog_scope("i", "o", "u", legacy)
    assert len(legacy.calls) == 1


@pytest.mark.asyncio
async def test_none_auth_rejects_identity_before_credentials() -> None:
    s = Store(instance={"_id": "i", "orgId": "o", "authMode": "none"})
    for instance_id, org_id in (("i", "wrong"), ("wrong", "o")):
        before = len(s.calls)
        with pytest.raises(CatalogScopeError):
            await load_catalog_scope(instance_id, org_id, "u", s)
        assert len(s.calls) == before + 1


@pytest.mark.asyncio
async def test_config_names_types_and_malformed_auth_are_bound_and_rejected() -> None:
    s = Store(auth={"isAuthenticated": True, "credentialGeneration": "g", "oauthTokens": {"accessToken": "t"}})
    first = await load_catalog_scope("i", "o", "u", s)
    for key, value in (("name", "Renamed"), ("typeId", "new-type")):
        s.data[get_mcp_instance_path("i")][key] = value
        next_scope = await load_catalog_scope("i", "o", "u", s)
        assert first.identity != next_scope.identity
        first = next_scope
    for auth in (
        {"isAuthenticated": True, "credentialGeneration": 7, "oauthTokens": {"accessToken": "t"}},
        {"isAuthenticated": 1, "credentialGeneration": "g", "oauthTokens": {"accessToken": "t"}},
        {"isAuthenticated": True, "credentialGeneration": "g"},
    ):
        s.data[get_mcp_credentials_path("i", "u")] = auth
        with pytest.raises(CatalogScopeError):
            await load_catalog_scope("i", "o", "u", s)


@pytest.mark.asyncio
async def test_cas_lost_to_authenticated_reconnect_adopts_new_generation() -> None:
    s = Store(auth={"isAuthenticated": True, "oauthTokens": {"accessToken": "old"}})
    s.cas_race = {"isAuthenticated": True, "credentialGeneration": "new", "oauthTokens": {"accessToken": "new-token"}}
    scope = await load_catalog_scope("i", "o", "u", s)
    assert scope.generation == "new"
    assert scope.auth["oauthTokens"]["accessToken"] == "new-token"
    assert s.data[get_mcp_credentials_path("i", "u")]["credentialGeneration"] == "new"


@pytest.mark.asyncio
async def test_sensitive_values_absent_from_repr_and_identity_and_post_fill_stale() -> (
    None
):
    s = Store(
        auth={
            "isAuthenticated": True,
            "credentialGeneration": "opaque-random",
            "oauthTokens": {"accessToken": "secret-token"},
        }
    )
    scope = await load_catalog_scope("i", "o", "u", s)
    assert "secret-token" not in repr(scope) and "opaque-random" not in repr(scope)
    assert "opaque-random" not in scope.identity
    s.data[get_mcp_credentials_path("i", "u")]["credentialGeneration"] = "replacement"
    assert not await scope_is_current(scope, s)


@pytest.mark.asyncio
async def test_noncredential_values_and_http_env_do_not_authorize_a_scope() -> None:
    for mode, transport, credentials in (
        ("oauth", "streamable_http", {"oauthTokens": {"accessToken": 1}}),
        ("api_token", "streamable_http", {"credentials": {"env": {"TOKEN": "secret"}}}),
        ("api_token", "stdio", {"credentials": {"env": {"UNAPPROVED": "secret"}}}),
        ("headers", "streamable_http", {"credentials": {"headerName": "X-Key", "headerValue": True}}),
    ):
        store = Store(
            instance={"_id": "i", "orgId": "o", "authMode": mode, "transport": transport, "requiredEnv": ["TOKEN"]},
            auth={"isAuthenticated": True, "credentialGeneration": "g", **credentials},
        )
        with pytest.raises(CatalogScopeError):
            await load_catalog_scope("i", "o", "u", store)


@pytest.mark.asyncio
async def test_allowlisted_stdio_credentials_authorize_only_their_owner() -> None:
    store = Store(
        instance={"_id": "i", "orgId": "o", "authMode": "api_token", "transport": "stdio", "requiredEnv": ["TOKEN"]},
        auth={"isAuthenticated": True, "credentialGeneration": "g", "credentials": {"env": {"TOKEN": "secret"}}},
    )
    scope = await load_catalog_scope("i", "o", "u", store)
    assert scope.owner_id == "u"
    with pytest.raises(CatalogScopeError):
        await load_catalog_scope("i", "o", "other", store)


@pytest.mark.asyncio
async def test_legacy_generation_migration_waits_for_rotated_token_persistence(monkeypatch) -> None:
    from app.agents.mcp import credential_lock

    monkeypatch.setattr(credential_lock, "CLUSTER_LOCK_POLL_SECONDS", 0.001)
    monkeypatch.setattr(credential_lock, "CLUSTER_LOCK_MAX_POLL_SECONDS", 0.01)
    store = Store()
    credential_path = get_mcp_credentials_path("i", "u")
    waiting = asyncio.Event()
    original = store.create_config_if_absent

    async def observe_claim(path, value, **kwargs) -> bool:
        created = await original(path, value, **kwargs)
        if not created:
            waiting.set()
        return created

    monkeypatch.setattr(store, "create_config_if_absent", observe_claim)
    async with credential_lock.credential_refresh_lock("i", "u", store):
        task = asyncio.create_task(load_catalog_scope("i", "o", "u", store))
        await asyncio.wait_for(waiting.wait(), timeout=1)
        before = copy.deepcopy(store.data[credential_path])
        assert "credentialGeneration" not in before
        after = copy.deepcopy(before)
        after["oauthTokens"] = {"accessToken": "rotated-access", "refreshToken": "rotated-refresh"}
        assert await store.compare_and_set_config(credential_path, before, after)
    scope = await asyncio.wait_for(task, timeout=1)
    assert scope.auth["oauthTokens"] == after["oauthTokens"]
    assert store.data[credential_path]["oauthTokens"]["refreshToken"] == "rotated-refresh"
