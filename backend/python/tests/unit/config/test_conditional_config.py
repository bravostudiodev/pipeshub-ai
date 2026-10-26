"""Atomic config updates must survive revocation and replacement-lease races."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from etcd3.client import Transactions

from app.config.configuration_service import ConfigurationService
from app.config.providers.encrypted_store import EncryptedKeyValueStore
from app.config.providers.etcd.etcd3_encrypted_store import Etcd3EncryptedKeyValueStore
from app.config.providers.etcd.etcd3_store import Etcd3DistributedKeyValueStore
from app.config.providers.in_memory_store import InMemoryKeyValueStore
from app.config.providers.redis.redis_store import RedisDistributedKeyValueStore


class NonceEncryption:
    def __init__(self) -> None:
        self.counter = 0

    def encrypt(self, text: str) -> str:
        self.counter += 1
        return f"nonce-{self.counter}:{text}"

    def decrypt(self, text: str) -> str:
        return text.split(":", 1)[1]


def make_store(kind: str) -> InMemoryKeyValueStore | EncryptedKeyValueStore | Etcd3EncryptedKeyValueStore:
    inner = InMemoryKeyValueStore(MagicMock())
    if kind == "memory":
        return inner
    cls = EncryptedKeyValueStore if kind == "encrypted" else Etcd3EncryptedKeyValueStore
    store = object.__new__(cls)
    store.logger = MagicMock()
    store.store = inner
    store.encryption_service = NonceEncryption()
    return store


def make_config(store) -> ConfigurationService:
    cfg = object.__new__(ConfigurationService)
    cfg.store = store
    cfg.cache = {}
    cfg.logger = MagicMock()
    cfg._publish_cache_invalidation = AsyncMock()
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "encrypted", "legacy_encrypted"])
async def test_conditional_update_delete_and_absence(kind) -> None:
    store = make_store(kind)
    await store.create_key("/credential", {"token": "old"})
    assert not await store.compare_and_set("/credential", {"token": "other"}, {"token": "bad"})
    assert await store.compare_and_set("/credential", {"token": "old"}, {"token": "new"})
    assert await store.get_key("/credential") == {"token": "new"}
    assert await store.compare_and_set("/credential", {"token": "new"}, None)
    assert not await store.compare_and_set("/credential", {"token": "new"}, {"token": "resurrected"})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["encrypted", "legacy_encrypted"])
async def test_encrypted_compare_cannot_overwrite_reconnect_after_decryption(kind) -> None:
    store = make_store(kind)
    await store.create_key("/credential", {"token": "old"})
    original = store.store.compare_and_set

    async def reconnect_before_write(key, expected, value) -> bool:
        await store.create_key(key, {"token": "reconnected"})
        return await original(key, expected, value)

    store.store.compare_and_set = reconnect_before_write
    assert not await store.compare_and_set("/credential", {"token": "old"}, {"token": "refreshed"})
    assert await store.get_key("/credential") == {"token": "reconnected"}


@pytest.mark.asyncio
async def test_config_ttl_claim_is_not_cached_and_conflicts_do_not_publish() -> None:
    store = InMemoryKeyValueStore(MagicMock())
    cfg = make_config(store)
    cfg.cache["/lease"] = "stale"
    assert await cfg.create_config_if_absent("/lease", {"owner": "a"}, ttl_seconds=60)
    assert "/lease" not in cfg.cache
    assert store.store["/lease"].expiry is not None
    cfg._publish_cache_invalidation.reset_mock()
    assert not await cfg.compare_and_set_config("/lease", {"owner": "b"}, None)
    cfg._publish_cache_invalidation.assert_not_awaited()
    assert await cfg.compare_and_set_config("/lease", {"owner": "a"}, None)
    cfg._publish_cache_invalidation.assert_awaited_once_with("/lease")


@pytest.mark.asyncio
async def test_conditional_store_error_propagates_and_invalidates_local_guess() -> None:
    store = MagicMock()
    store.compare_and_set = AsyncMock(side_effect=ConnectionError("unavailable"))
    cfg = make_config(store)
    cfg.cache["/credential"] = "old"
    with pytest.raises(ConnectionError):
        await cfg.compare_and_set_config("/credential", "old", "new")
    assert "/credential" not in cfg.cache


@pytest.mark.asyncio
async def test_redis_lua_is_atomic_and_preserves_ttl() -> None:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    pytest.importorskip("lupa")
    client = fakeredis.FakeRedis()
    store = object.__new__(RedisDistributedKeyValueStore)
    store._key_namespace_prefix = "company:"
    store.key_prefix = "kv:"
    store.serializer = lambda value: json.dumps(value).encode()
    store.deserializer = json.loads
    store._get_client = lambda: client
    store._notify_watchers = AsyncMock()
    try:
        await client.set("company:kv:/credential", json.dumps({"token": "old"}), ex=60)
        results = await asyncio.gather(*[
            store.compare_and_set("/credential", {"token": "old"}, {"token": str(i)}) for i in range(8)
        ])
        assert results.count(True) == 1
        assert 0 < await client.ttl("company:kv:/credential") <= 60
        current = await store.get_key("/credential")
        assert not await store.compare_and_set("/credential", {"token": "old"}, None)
        assert await store.compare_and_set("/credential", current, None)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("delete", [True, False])
async def test_etcd_transaction_compares_revision_and_preserves_lease(delete) -> None:
    store = object.__new__(Etcd3DistributedKeyValueStore)
    store.deserializer = json.loads
    client = MagicMock()
    client.transactions = Transactions()
    client.get.return_value = (b'{"token":"old"}', SimpleNamespace(mod_revision=42, lease_id=77))
    client.transaction.return_value = (True, [])

    async def run(operation) -> bool:
        return operation(client)

    store._run = run
    assert await store.compare_and_set("/credential", {"token": "old"}, None if delete else {"token": "new"})
    transaction = client.transaction.call_args.kwargs
    comparison = transaction["compare"][0].build_message()
    assert comparison.mod_revision == 42
    operation = transaction["success"][0]
    assert operation.key == "/credential"
    if not delete:
        assert operation.lease == 77
    client.transaction.return_value = (False, [])
    assert not await store.compare_and_set("/credential", {"token": "old"}, None)
