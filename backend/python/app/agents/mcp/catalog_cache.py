"""Private MCP metadata catalogs; authorization is never cached.

Single-flight is process/loop-local. Random, expiring epoch pointers make late
writes unreachable after invalidation or pointer expiry, including across replicas.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
import time
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agents.mcp.catalog_scope import CatalogScopeError, load_catalog_scope
from app.utils.env_utils import env_int

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from app.agents.mcp.catalog_scope import CatalogScope

SCHEMA_VERSION = 1
TTL_ENV = "MCP_TOOL_CACHE_TTL_SECONDS"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
# A server sending `ttlMs: 0` (the protocol default when its author set nothing) or an
# unusable hint gets this short window instead: the pre-call check still verifies the list.
STALE_TTL_ENV = "MCP_TOOL_CACHE_STALE_TTL_SECONDS"
DEFAULT_STALE_TTL_SECONDS = 15 * 60
FILL_TIMEOUT_SECONDS = 60
# The invalidation pointer must outlive every entry written under it, or entries
# become unreachable early.
_EPOCH_MARGIN_SECONDS = 300
MAX_ENTRY_BYTES = 512 * 1024
MAX_TOOLS = 1000
MAX_SCHEMA_BYTES = 128 * 1024
_MAX_LOOPS = 8
_MAX_LOCKS = 256
# Provider listings in flight: per instance, so one stalled provider only queues its own
# listings, and per process, as a resource ceiling across every user and server.
_LISTINGS_PER_INSTANCE = 4
_LISTINGS_PER_PROCESS = 64


@dataclass
class _LoopState:
    listings: asyncio.Semaphore
    locks: OrderedDict[str, asyncio.Lock]
    overflow: asyncio.Lock
    instance_listings: OrderedDict[str, asyncio.Semaphore]


_LOOPS: OrderedDict[asyncio.AbstractEventLoop, _LoopState] = OrderedDict()


def ttl_seconds() -> int:
    """`MCP_TOOL_CACHE_TTL_SECONDS`, 24 h by default; 0 turns the cache off."""
    return env_int(TTL_ENV, DEFAULT_TTL_SECONDS, lo=0, hi=7 * 24 * 60 * 60) or 0


def stale_ttl_seconds() -> int:
    return env_int(STALE_TTL_ENV, DEFAULT_STALE_TTL_SECONDS, lo=0, hi=24 * 60 * 60) or 0


def _epoch_ttl_seconds() -> int:
    return ttl_seconds() + _EPOCH_MARGIN_SECONDS


def entry_ttl(hint: float | None) -> int:
    """Seconds to keep a listing: ours, or the server's own hint when shorter. 0 = don't cache."""
    limit = ttl_seconds()
    if hint is None:
        ttl = float(limit)
    elif hint == 0:
        ttl = float(min(limit, stale_ttl_seconds()))
    else:
        ttl = min(float(limit), max(0.0, hint))
    # Fractional hints are rounded down: never outlive provider permission.
    return math.floor(ttl) if ttl >= 1 else 0


class CatalogUnavailable(RuntimeError):
    """Catalog coordination is temporarily unavailable, not an auth rejection."""


class CatalogInvalidated(RuntimeError):
    """Authority or the catalog changed before an operation completed."""


@dataclass(frozen=True)
class CatalogResult:
    scope: CatalogScope
    tools: list[dict[str, Any]]
    instructions: str | None
    cached: bool


def _scope_key(scope: CatalogScope) -> str:
    return hashlib.sha256(f"mcp-catalog-v{SCHEMA_VERSION}:{scope.identity}".encode()).hexdigest()


def _path(key: str) -> str:
    return f"/services/mcp/catalog/v{SCHEMA_VERSION}/{key}"


def _epoch_path(key: str) -> str:
    return f"/services/mcp/catalog-epoch/v{SCHEMA_VERSION}/{key}"


def _loop_state() -> _LoopState:
    loop = asyncio.get_running_loop()
    state = _LOOPS.get(loop)
    if state is None:
        for old_loop in list(_LOOPS):
            if old_loop.is_closed() or not old_loop.is_running():
                _LOOPS.pop(old_loop)
        if len(_LOOPS) >= _MAX_LOOPS:
            raise CatalogUnavailable("MCP discovery is busy; try again shortly")
        state = _LoopState(asyncio.Semaphore(_LISTINGS_PER_PROCESS), OrderedDict(), asyncio.Lock(), OrderedDict())
        _LOOPS[loop] = state
    return state


def _instance_listings(state: _LoopState, instance_id: str) -> asyncio.Semaphore:
    semaphore = state.instance_listings.get(instance_id)
    if semaphore is None:
        if len(state.instance_listings) >= _MAX_LOCKS:
            for old_id, old in list(state.instance_listings.items()):
                if old._value == _LISTINGS_PER_INSTANCE and not getattr(old, "_waiters", None):
                    state.instance_listings.pop(old_id)
                    break
        semaphore = asyncio.Semaphore(_LISTINGS_PER_INSTANCE)
        state.instance_listings[instance_id] = semaphore
    state.instance_listings.move_to_end(instance_id)
    return semaphore


def _coordination(key: str) -> asyncio.Lock:
    state = _loop_state()
    locks, overflow = state.locks, state.overflow
    lock = locks.get(key)
    if lock is None:
        if len(locks) >= _MAX_LOCKS:
            for old_key, old_lock in list(locks.items()):
                # A woken waiter still owns its place even before locked() becomes true.
                if not old_lock.locked() and not getattr(old_lock, "_waiters", None):
                    locks.pop(old_key)
                    break
        if len(locks) >= _MAX_LOCKS:
            return overflow
        lock = asyncio.Lock()
        locks[key] = lock
    locks.move_to_end(key)
    return lock


@asynccontextmanager
async def listing_slot(instance_id: str) -> AsyncIterator[None]:
    """One provider listing for `instance_id`, within its own bound and the process bound.
    Used by catalog fills and by execution-session validation alike."""
    state = _loop_state()
    async with asyncio.timeout(FILL_TIMEOUT_SECONDS), _instance_listings(state, instance_id), state.listings:
        yield


def _normalize_listing(listing: Any) -> tuple[list[dict[str, Any]], str | None, float | None]:  # noqa: ANN401
    source = listing.get("tools") if isinstance(listing, dict) else getattr(listing, "tools", None)
    if not isinstance(source, list) or len(source) > MAX_TOOLS:
        raise ValueError("MCP provider returned an invalid tool catalog")
    tools: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in source:
        raw = item.model_dump(by_alias=True, exclude_none=True) if hasattr(item, "model_dump") else item
        if not isinstance(raw, dict):
            raise ValueError("MCP provider returned an invalid tool schema")
        name = raw.get("name")
        schema = raw.get("inputSchema", raw.get("input_schema"))
        if not isinstance(name, str) or not name or name in names or not isinstance(schema, dict):
            raise ValueError("MCP provider returned an incomplete tool schema")
        if len(json.dumps(schema, allow_nan=False).encode()) > MAX_SCHEMA_BYTES:
            raise ValueError("MCP provider returned an oversized tool schema")
        tool = {"name": name, "inputSchema": schema}
        for field in ("description", "outputSchema", "annotations"):
            value = raw.get(field, raw.get("output_schema") if field == "outputSchema" else None)
            if value is not None:
                if not isinstance(value, str if field == "description" else dict):
                    raise ValueError("MCP provider returned invalid tool metadata")
                tool[field] = value
        tools.append(tool)
        names.add(name)
    instructions = listing.get("instructions") if isinstance(listing, dict) else getattr(listing, "instructions", None)
    if instructions is not None and (not isinstance(instructions, str) or len(instructions) > 100_000):
        raise ValueError("MCP provider returned invalid server instructions")
    ttl = listing.get("ttl_seconds") if isinstance(listing, dict) else getattr(listing, "ttl_seconds", None)
    if isinstance(ttl, bool) or (ttl is not None and (not isinstance(ttl, (int, float)) or not math.isfinite(ttl))):
        ttl = 0
    # Also reject non-JSON values nested inside metadata.
    encoded = json.dumps({"tools": tools, "instructions": instructions}, allow_nan=False)
    # Detach nested objects even when a backend returns its stored objects by reference.
    detached = json.loads(encoded)
    return detached["tools"], detached["instructions"], ttl


def _valid_entry(raw: Any) -> tuple[list[dict[str, Any]], str | None] | None:  # noqa: ANN401
    if not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] != SCHEMA_VERSION:
        return None
    try:
        if len(json.dumps(raw, allow_nan=False).encode()) > MAX_ENTRY_BYTES:
            return None
        expires = raw.get("expiresAt")
        now = time.time()
        if isinstance(expires, bool) or not isinstance(expires, (float, int)) or not math.isfinite(expires):
            return None
        if not now < expires <= now + ttl_seconds():
            return None
        tools, instructions, _ = _normalize_listing(raw)
        return tools, instructions
    except (TypeError, ValueError, OverflowError):
        return None


async def _current(scope: CatalogScope, config_service: Any) -> CatalogScope:  # noqa: ANN401
    try:
        fresh = await load_catalog_scope(scope.instance_id, scope.org_id, scope.owner_id, config_service)
    except CatalogScopeError as exc:
        raise CatalogInvalidated("MCP authorization changed during discovery") from exc
    if fresh.identity != scope.identity:
        raise CatalogInvalidated("MCP authorization or configuration changed during discovery")
    return fresh


async def _read_epoch(key: str, config_service: Any) -> str:  # noqa: ANN401
    epoch = await config_service.get_config(key, default=None, use_cache=False, raise_on_error=True)
    if epoch is None:
        await config_service.create_config_if_absent(key, secrets.token_hex(16), ttl_seconds=_epoch_ttl_seconds())
        epoch = await config_service.get_config(key, default=None, use_cache=False, raise_on_error=True)
    if not isinstance(epoch, str) or not epoch:
        raise CatalogUnavailable("MCP catalog epoch unavailable")
    return epoch


async def get_for_owner(
    instance_id: str, org_id: str, owner_id: str, config_service: Any,  # noqa: ANN401
    discover: Callable[[CatalogScope], Awaitable[Any]],
) -> CatalogResult:
    """Bound queue, storage and provider waits; authority failures never fall back."""
    async with asyncio.timeout(FILL_TIMEOUT_SECONDS):
        scope = await load_catalog_scope(instance_id, org_id, owner_id, config_service)
        key = _scope_key(scope)
        epoch_key = _epoch_path(key)
        try:
            epoch = await _read_epoch(epoch_key, config_service)
        except Exception:
            epoch = None
        lock = _coordination(key)
        async with lock:
            value_key = _path(hashlib.sha256(f"{key}:{epoch}".encode()).hexdigest()) if epoch else None
            if value_key is not None:
                try:
                    raw = await config_service.get_config(value_key, default=None, use_cache=False, raise_on_error=True)
                    parsed = _valid_entry(raw)
                    current_epoch = await config_service.get_config(epoch_key, default=None, use_cache=False, raise_on_error=True)
                except Exception:
                    parsed = None
                    epoch = None
                if parsed is not None and current_epoch == epoch:
                    fresh = await _current(scope, config_service)
                    # Never return a cache hit when its invalidation pointer is unavailable.
                    try:
                        current_epoch = await config_service.get_config(epoch_key, default=None, use_cache=False, raise_on_error=True)
                    except Exception:
                        epoch = None
                        current_epoch = None
                    if epoch is not None and current_epoch == epoch:
                        return CatalogResult(fresh, parsed[0], parsed[1], True)
            scope = await _current(scope, config_service)
            async with listing_slot(instance_id):
                listing = await discover(scope)
            tools, instructions, hint = _normalize_listing(listing)
            scope = await _current(scope, config_service)
            if epoch is not None and value_key is not None:
                try:
                    current_epoch = await config_service.get_config(epoch_key, default=None, use_cache=False, raise_on_error=True)
                except Exception:
                    current_epoch = epoch = None
                if epoch is not None and current_epoch != epoch:
                    raise CatalogInvalidated("MCP tool catalog changed during discovery")
                ttl = entry_ttl(hint)
                if epoch is not None and ttl >= 1:
                    body = {"schemaVersion": SCHEMA_VERSION, "expiresAt": time.time() + ttl,
                            "tools": tools, "instructions": instructions}
                    if len(json.dumps(body, allow_nan=False).encode()) <= MAX_ENTRY_BYTES:
                        # Cache persistence is optional, current authority is not.
                        with suppress(Exception):
                            await config_service.set_config(value_key, json.loads(json.dumps(body)), ttl=ttl)
            scope = await _current(scope, config_service)
            if epoch is not None:
                try:
                    latest_epoch = await config_service.get_config(epoch_key, default=None, use_cache=False, raise_on_error=True)
                except Exception:
                    latest_epoch = epoch  # Live data remains usable; do not fall back to a cached value.
                if latest_epoch != epoch:
                    raise CatalogInvalidated("MCP tool catalog changed during publication")
            return CatalogResult(scope, tools, instructions, False)


async def invalidate_scope(scope: CatalogScope, config_service: Any) -> None:  # noqa: ANN401
    """Random epochs never reuse a namespace, even when a pointer expires."""
    key = _epoch_path(_scope_key(scope))
    for _ in range(4):
        old = await config_service.get_config(key, default=None, use_cache=False, raise_on_error=True)
        new = secrets.token_hex(16)
        if old is None:
            if await config_service.create_config_if_absent(key, new, ttl_seconds=_epoch_ttl_seconds()):
                return
        elif await config_service.compare_and_set_config(key, old, new):
            return
    raise CatalogUnavailable("Could not invalidate MCP catalog")
