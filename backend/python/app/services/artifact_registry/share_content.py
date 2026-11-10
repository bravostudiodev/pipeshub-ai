"""Narrow content access for a previously validated artifact share.

Only a trusted server-side caller may supply ``actor``. This service does not
validate bearer tokens or account status: the caller must do that on every
request before invoking it, and must not expose this as an ordinary read bypass.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

from .access import ArtifactNotFoundError
from .deck_archive import (
    DeckArchiveCache,
    DeckFile,
    InvalidDeckArchive,
    deck_archive_cache,
    get_cached_deck_file_async,
    read_deck_archive,
)
from .share_authorization import ArtifactShareAuthorization

if TYPE_CHECKING:
    from app.services.artifact_registry.models import Actor
    from app.services.artifact_registry.registry import ArtifactRegistryService
    from app.services.graph_db.interface.graph_db_provider import IGraphDBProvider


class ArtifactShareContent:
    def __init__(
        self, graph: IGraphDBProvider, registry: ArtifactRegistryService
    ) -> None:
        self._authorization = ArtifactShareAuthorization(graph)
        self._registry = registry

    async def get_content(
        self, *, actor: Actor, artifact_id: str, version: int, pinned_hash: str
    ) -> bytes:
        # Recheck ownership/visibility and the precise version on every call.
        expected_hash = await self._authorization.authorize(actor, artifact_id, version)
        if not hmac.compare_digest(expected_hash, pinned_hash):
            raise ArtifactNotFoundError("Artifact version unavailable")
        # The registry rechecks read access and uses its existing storage version
        # mapping and blob abstraction; no storage URL is returned to a viewer.
        content = await self._registry.get_content(
            actor=actor, artifact_id=artifact_id, version=version
        )
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_hash):
            raise ArtifactNotFoundError("Artifact version unavailable")
        return content

    async def get_deck_file(
        self,
        *,
        actor: Actor,
        artifact_id: str,
        version: int,
        pinned_hash: str,
        path: str,
        cache: DeckArchiveCache = deck_archive_cache,
    ) -> DeckFile:
        """Serve one file after reauthorizing the share; cache only immutable bytes."""
        expected_hash = await self._authorization.authorize(actor, artifact_id, version)
        if not hmac.compare_digest(expected_hash, pinned_hash):
            raise ArtifactNotFoundError("Artifact version unavailable")
        key = (actor.org_id, actor.user_id, artifact_id, version, expected_hash)

        async def load_archive() -> dict[str, DeckFile]:
            content = await self._registry.get_content(
                actor=actor, artifact_id=artifact_id, version=version
            )
            if not hmac.compare_digest(
                hashlib.sha256(content).hexdigest(), expected_hash
            ):
                raise ArtifactNotFoundError("Artifact version unavailable")
            return read_deck_archive(content)

        try:
            return await get_cached_deck_file_async(cache, key, path, load_archive)
        except InvalidDeckArchive:
            raise ArtifactNotFoundError("Artifact version unavailable") from None
