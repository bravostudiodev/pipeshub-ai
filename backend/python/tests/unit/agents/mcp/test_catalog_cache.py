import asyncio
import copy
from typing import Any

import pytest

from app.agents.constants.mcp_server_constants import (
    get_mcp_credentials_path,
    get_mcp_instance_path,
)
from app.agents.mcp.catalog_cache import (
    CatalogInvalidated,
    get_for_owner,
    invalidate_scope,
)
from app.agents.mcp.catalog_scope import CatalogScopeError, load_catalog_scope


class Store:
    def __init__(self) -> None:
        self.data = {
            get_mcp_instance_path("i"): {"_id": "i", "orgId": "o", "authMode": "oauth"},
            get_mcp_credentials_path("i", "u"): {
                "isAuthenticated": True, "credentialGeneration": "g",
                "oauthTokens": {"accessToken": "secret"},
            },
        }
        self.listings = 0
        self.fail_cache = False
        self.race_revoke = False

    async def get_config(self, key: str, default: Any = None, **kwargs: Any) -> Any:  # noqa: ANN401
        if self.fail_cache and "/catalog/" in key:
            raise RuntimeError("cache down")
        return copy.deepcopy(self.data.get(key, default))

    async def set_config(self, key: str, value: Any, **kwargs: Any) -> bool:  # noqa: ANN401
        if self.fail_cache:
            return False
        self.data[key] = copy.deepcopy(value)
        return True

    async def create_config_if_absent(self, key: str, value: Any, **kwargs: Any) -> bool:  # noqa: ANN401
        if key in self.data:
            return False
        self.data[key] = value
        return True

    async def compare_and_set_config(self, key: str, old: Any, new: Any) -> bool:  # noqa: ANN401
        if self.data.get(key) != old:
            return False
        self.data[key] = new
        return True

    async def live(self, scope: Any) -> dict[str, Any]:  # noqa: ANN401
        self.listings += 1
        if self.race_revoke:
            self.data[get_mcp_credentials_path("i", "u")] = {"isAuthenticated": False}
        return {"tools": [{"name": "search", "description": "Search", "inputSchema": {"type": "object", "properties": {}}, "outputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}], "instructions": "Read-only guidance"}


@pytest.mark.asyncio
async def test_round_trip_private_real_schema_and_cache_hit_skips_discovery() -> None:
    store = Store()
    first = await get_for_owner("i", "o", "u", store, store.live)
    assert not first.cached and first.instructions == "Read-only guidance"
    assert first.tools[0]["outputSchema"] == {"type": "object"}
    second = await get_for_owner("i", "o", "u", store, store.live)
    assert second.cached and second.tools == first.tools and store.listings == 1


@pytest.mark.asyncio
async def test_returned_metadata_cannot_mutate_stored_contracts() -> None:
    class ReferenceStore(Store):
        async def get_config(self, key, default=None, **kwargs) -> object:
            return self.data.get(key, default)

        async def set_config(self, key, value, **kwargs) -> bool:
            self.data[key] = value
            return True

    store = ReferenceStore()
    first = await get_for_owner("i", "o", "u", store, store.live)
    first.tools[0]["inputSchema"]["properties"]["invented"] = {"type": "string"}
    second = await get_for_owner("i", "o", "u", store, store.live)
    assert "invented" not in second.tools[0]["inputSchema"]["properties"]
    second.tools[0]["inputSchema"]["properties"]["invented"] = {"type": "number"}
    third = await get_for_owner("i", "o", "u", store, store.live)
    assert "invented" not in third.tools[0]["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_owner_org_generation_and_config_are_isolated() -> None:
    store = Store()
    await get_for_owner("i", "o", "u", store, store.live)
    store.data[get_mcp_credentials_path("i", "v")] = {"isAuthenticated": True, "credentialGeneration": "g", "oauthTokens": {"accessToken": "v"}}
    assert not (await get_for_owner("i", "o", "v", store, store.live)).cached
    store.data[get_mcp_instance_path("i")]["url"] = "https://changed.invalid"
    assert not (await get_for_owner("i", "o", "u", store, store.live)).cached
    with pytest.raises(CatalogScopeError):
        await get_for_owner("i", "different", "u", store, store.live)


@pytest.mark.asyncio
async def test_authority_failure_and_revoke_fail_closed() -> None:
    store = Store()
    store.data.pop(get_mcp_credentials_path("i", "u"))
    with pytest.raises(CatalogScopeError):
        await get_for_owner("i", "o", "u", store, store.live)
    assert store.listings == 0


@pytest.mark.asyncio
async def test_reconnect_during_fill_cannot_publish_or_return_catalog() -> None:
    store = Store()
    store.race_revoke = True
    with pytest.raises(CatalogInvalidated):
        await get_for_owner("i", "o", "u", store, store.live)
    assert not any("/catalog/v1/" in key for key in store.data)


@pytest.mark.asyncio
async def test_cache_failure_falls_back_only_after_authority_and_live_discovery() -> None:
    store = Store()
    store.fail_cache = True
    result = await get_for_owner("i", "o", "u", store, store.live)
    assert not result.cached and store.listings == 1 and result.tools


@pytest.mark.asyncio
async def test_schema_less_or_oversized_catalog_is_not_fabricated_or_cached() -> None:
    store = Store()
    async def bad(scope: Any) -> dict[str, Any]:  # noqa: ANN401
        store.listings += 1
        return {"tools": [{"name": "fake"}]}
    with pytest.raises(ValueError):
        await get_for_owner("i", "o", "u", store, bad)
    assert not any("/catalog/v1/" in key for key in store.data)


@pytest.mark.asyncio
async def test_process_singleflight_and_invalidation_epoch() -> None:
    store = Store()
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(scope) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return await store.live(scope)

    tasks = [asyncio.create_task(get_for_owner("i", "o", "u", store, delayed)) for _ in range(5)]
    await asyncio.wait_for(entered.wait(), timeout=1)
    release.set()
    results = await asyncio.gather(*tasks)
    assert store.listings == 1
    assert sum(item.cached for item in results) == 4
    scope = await load_catalog_scope("i", "o", "u", store)
    await invalidate_scope(scope, store)
    assert not (await get_for_owner("i", "o", "u", store, store.live)).cached
    assert store.listings == 2


@pytest.mark.asyncio
async def test_strict_missing_epoch_invalidation_and_fill_race() -> None:
    store = Store()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed(scope: Any) -> dict[str, Any]:  # noqa: ANN401
        entered.set()
        await release.wait()
        return await store.live(scope)

    task = asyncio.create_task(get_for_owner("i", "o", "u", store, delayed))
    await entered.wait()
    scope = await load_catalog_scope("i", "o", "u", store)
    await invalidate_scope(scope, store)
    release.set()
    with pytest.raises(CatalogInvalidated):
        await task


@pytest.mark.asyncio
async def test_epoch_expiry_cannot_resurrect_a_still_unexpired_catalog() -> None:
    store = Store()
    await get_for_owner("i", "o", "u", store, store.live)
    key = next(key for key in store.data if "/catalog-epoch/" in key)
    old_epoch = store.data.pop(key)
    result = await get_for_owner("i", "o", "u", store, store.live)
    assert not result.cached and store.listings == 2
    assert store.data[key] != old_epoch


@pytest.mark.asyncio
async def test_epoch_outage_bypasses_an_existing_cache_entry(monkeypatch) -> None:
    store = Store()
    await get_for_owner("i", "o", "u", store, store.live)
    original = store.get_config

    async def fail_epoch(key, **kwargs) -> object:
        if "/catalog-epoch/" in key:
            raise RuntimeError("metadata unavailable")
        return await original(key, **kwargs)

    monkeypatch.setattr(store, "get_config", fail_epoch)
    result = await get_for_owner("i", "o", "u", store, store.live)
    assert not result.cached and store.listings == 2


async def _listings_after_two_fills(hint: object) -> int:
    store = Store()

    async def hinted(scope, store=store) -> dict[str, Any]:
        result = await store.live(scope)
        result["ttl_seconds"] = hint
        return result

    await get_for_owner("i", "o", "u", store, hinted)
    await get_for_owner("i", "o", "u", store, hinted)
    return store.listings


@pytest.mark.asyncio
async def test_a_sub_second_provider_hint_is_not_cached() -> None:
    assert await _listings_after_two_fills(0.5) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", [0, True, float("nan"), "forever"])
async def test_zero_or_unusable_hints_get_only_the_short_window(hint: object, monkeypatch) -> None:
    assert await _listings_after_two_fills(hint) == 1
    # The short window, not the full lifetime: with it off, nothing is kept.
    monkeypatch.setenv("MCP_TOOL_CACHE_STALE_TTL_SECONDS", "0")
    assert await _listings_after_two_fills(hint) == 2


def test_entry_lifetime_defaults_to_a_day_and_honors_shorter_hints(monkeypatch) -> None:
    from app.agents.mcp.catalog_cache import entry_ttl

    assert entry_ttl(None) == 24 * 60 * 60
    assert entry_ttl(120.9) == 120
    assert entry_ttl(10 ** 9) == 24 * 60 * 60
    monkeypatch.setenv("MCP_TOOL_CACHE_TTL_SECONDS", "0")
    assert entry_ttl(None) == 0


@pytest.mark.asyncio
async def test_invalidation_during_publication_cannot_return_an_old_catalog(monkeypatch) -> None:
    store = Store()
    original = store.set_config

    async def invalidate_before_write(key, value, **kwargs) -> bool:
        scope = await load_catalog_scope("i", "o", "u", store)
        await invalidate_scope(scope, store)
        return await original(key, value, **kwargs)

    monkeypatch.setattr(store, "set_config", invalidate_before_write)
    with pytest.raises(CatalogInvalidated):
        await get_for_owner("i", "o", "u", store, store.live)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "encrypted", "legacy_encrypted"])
async def test_catalog_ttl_write_expires_in_storage_without_a_local_write_cache(kind) -> None:
    from tests.unit.config.test_conditional_config import make_config, make_store

    store = make_store(kind)
    config = make_config(store)
    key = "/services/mcp/catalog/v1/ttl-test"
    config.cache[key] = {"old": True}
    assert await config.set_config(key, {"tools": []}, ttl=1)
    assert key not in config.cache
    inner = store if kind == "memory" else store.store
    assert inner.store[key].expiry is not None
    inner.store[key].expiry = -1
    assert await config.get_config(key, use_cache=False, raise_on_error=True) is None


@pytest.mark.asyncio
async def test_a_stalled_provider_does_not_hold_up_other_instances() -> None:
    from app.agents.mcp import catalog_cache

    stalled = asyncio.Event()
    holders = [
        asyncio.create_task(_hold_listing(catalog_cache, "stalled-instance", stalled))
        for _ in range(catalog_cache._LISTINGS_PER_INSTANCE)
    ]
    await asyncio.sleep(0)
    try:
        async with asyncio.timeout(1):
            async with catalog_cache.listing_slot("healthy-instance"):
                pass
    finally:
        stalled.set()
        await asyncio.gather(*holders)


async def _hold_listing(catalog_cache, instance_id: str, release: asyncio.Event) -> None:
    async with catalog_cache.listing_slot(instance_id):
        await release.wait()
