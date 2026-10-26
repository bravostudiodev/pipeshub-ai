"""Cross-process serialization of refresh-token rotation through the config store."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.agents.constants.mcp_server_constants import get_mcp_refresh_lock_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.config.configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

CLUSTER_LOCK_TTL_SECONDS = 60
CLUSTER_LOCK_WAIT_SECONDS = 20.0
CLUSTER_LOCK_POLL_SECONDS = 0.05
CLUSTER_LOCK_MAX_POLL_SECONDS = 1.0


class MCPCredentialLockError(RuntimeError):
    """A refresh lease could not be obtained, or its ownership was lost."""


@dataclass
class RefreshLease:
    key: str
    owner: dict[str, str]
    config_service: ConfigurationService

    async def assert_owned(self) -> None:
        current = await self.config_service.get_config(self.key, default=None, use_cache=False, raise_on_error=True)
        if current != self.owner:
            raise MCPCredentialLockError("The connection refresh lease expired or changed owner")


async def _try_acquire(config_service: ConfigurationService, key: str, owner: dict[str, str]) -> bool:
    try:
        return await config_service.create_config_if_absent(key, owner, ttl_seconds=CLUSTER_LOCK_TTL_SECONDS)
    except Exception:
        # The write may have landed before the failure; release it if it is ours, so the
        # lease is not left to block every refresh until it expires.
        try:
            await config_service.compare_and_set_config(key, owner, None)
        except Exception as cleanup_exc:
            logger.warning("MCP refresh lease cleanup failed (%s); it will expire", type(cleanup_exc).__name__)
        raise


@asynccontextmanager
async def credential_refresh_lock(
    instance_id: str, owner_id: str, config_service: ConfigurationService,
) -> AsyncIterator[RefreshLease]:
    key = get_mcp_refresh_lock_path(instance_id, owner_id)
    owner = {"owner": uuid.uuid4().hex}
    deadline = time.monotonic() + CLUSTER_LOCK_WAIT_SECONDS
    # Backs off: many calls can hit one expired token at once, and each poll is a store round trip.
    wait = CLUSTER_LOCK_POLL_SECONDS
    while not await _try_acquire(config_service, key, owner):
        if time.monotonic() >= deadline:
            raise MCPCredentialLockError("Another request is still refreshing this connection")
        await asyncio.sleep(min(wait, max(0.0, deadline - time.monotonic())))
        wait = min(wait * 2, CLUSTER_LOCK_MAX_POLL_SECONDS)
    try:
        yield RefreshLease(key, owner, config_service)
    finally:
        try:
            # Atomic comparison prevents an expired holder deleting a replacement lease.
            await config_service.compare_and_set_config(key, owner, None)
        except Exception as exc:
            logger.warning("MCP refresh lease cleanup failed (%s); it will expire", type(exc).__name__)
