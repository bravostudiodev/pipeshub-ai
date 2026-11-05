"""Owner and visibility checks for publishing an artifact version.

This policy does not authorize access by a share token. Callers must also
verify the account is active and enforce share expiry/revocation on every read.
"""

from __future__ import annotations

import re
from typing import Any

from app.config.constants.arangodb import CollectionNames

from .access import AccessDeniedError, AccessPolicy, ArtifactNotFoundError
from .gallery import ArtifactDisplayPolicy, ArtifactGalleryService
from .models import Actor


class ArtifactShareAuthorization:
    def __init__(self, graph: Any) -> None:
        self._graph = graph
        self._access = AccessPolicy(graph)
        self._gallery = ArtifactGalleryService(graph)

    async def authorize(self, actor: Actor, artifact_id: str, version: int) -> str:
        """Fail closed unless this actor owns a visible artifact and version."""
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ArtifactNotFoundError("Artifact version not found")
        try:
            await self._access.authorize_write(actor, artifact_id)
            artifact = await self._graph.get_document(artifact_id, CollectionNames.ARTIFACTS.value)
            if not artifact or not ArtifactDisplayPolicy.is_user_visible_doc(artifact):
                raise ArtifactNotFoundError("Artifact not found")
            detail = await self._gallery.get(actor, artifact_id)
        except AccessDeniedError:
            # Readers must not be told whether publication would otherwise work.
            raise ArtifactNotFoundError("Artifact not found") from None
        selected = next((item for item in detail.versions if item.version == version), None)
        if selected is None or not re.fullmatch(r"[0-9a-f]{64}", selected.content_hash or ""):
            # A verified hash is necessary to detect a concurrent version bump
            # between storage-version resolution and reading the blob.
            raise ArtifactNotFoundError("Artifact version not found")
        return selected.content_hash
