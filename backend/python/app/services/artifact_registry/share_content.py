"""Narrow content access for a previously validated artifact share.

Only a trusted server-side caller may supply ``actor``. This service does not
validate bearer tokens or account status: the caller must do that on every
request before invoking it, and must not expose this as an ordinary read bypass.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from .access import ArtifactNotFoundError

from .models import Actor
from .share_authorization import ArtifactShareAuthorization


class ArtifactShareContent:
    def __init__(self, graph: Any, registry: Any) -> None:
        self._authorization = ArtifactShareAuthorization(graph)
        self._registry = registry

    async def get_content(self, *, actor: Actor, artifact_id: str, version: int, pinned_hash: str) -> bytes:
        # Recheck ownership/visibility and the precise version on every call.
        expected_hash = await self._authorization.authorize(actor, artifact_id, version)
        if not hmac.compare_digest(expected_hash, pinned_hash):
            raise ArtifactNotFoundError("Artifact version unavailable")
        # The registry rechecks read access and uses its existing storage version
        # mapping and blob abstraction; no storage URL is returned to a viewer.
        content = await self._registry.get_content(actor=actor, artifact_id=artifact_id, version=version)
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_hash):
            raise ArtifactNotFoundError("Artifact version unavailable")
        return content
