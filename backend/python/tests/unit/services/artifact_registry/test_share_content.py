import hashlib
from unittest.mock import AsyncMock

import pytest

from app.services.artifact_registry.models import Actor
from app.services.artifact_registry.share_content import ArtifactShareContent

HASH = hashlib.sha256(b"version one").hexdigest()
ACTOR = Actor(user_id="owner", org_id="org")


@pytest.mark.asyncio
async def test_content_rechecks_authority_and_loads_pinned_version():
    registry = AsyncMock()
    registry.get_content.return_value = b"version one"
    service = ArtifactShareContent(AsyncMock(), registry)
    service._authorization.authorize = AsyncMock(return_value=HASH)
    assert await service.get_content(actor=ACTOR, artifact_id="artifact", version=1, pinned_hash=HASH) == b"version one"
    service._authorization.authorize.assert_awaited_once_with(ACTOR, "artifact", 1)
    registry.get_content.assert_awaited_once_with(actor=ACTOR, artifact_id="artifact", version=1)


@pytest.mark.asyncio
async def test_denied_authority_never_reads_content():
    registry = AsyncMock()
    service = ArtifactShareContent(AsyncMock(), registry)
    service._authorization.authorize = AsyncMock(side_effect=PermissionError("denied"))
    with pytest.raises(PermissionError):
        await service.get_content(actor=ACTOR, artifact_id="artifact", version=1, pinned_hash=HASH)
    registry.get_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_content_during_version_race_is_not_returned():
    registry = AsyncMock()
    registry.get_content.return_value = b"newer version"
    service = ArtifactShareContent(AsyncMock(), registry)
    service._authorization.authorize = AsyncMock(return_value=HASH)
    with pytest.raises(LookupError):
        await service.get_content(actor=ACTOR, artifact_id="artifact", version=1, pinned_hash=HASH)


@pytest.mark.asyncio
async def test_changed_version_metadata_is_rejected():
    registry = AsyncMock()
    service = ArtifactShareContent(AsyncMock(), registry)
    service._authorization.authorize = AsyncMock(return_value="a" * 64)
    with pytest.raises(LookupError):
        await service.get_content(actor=ACTOR, artifact_id="artifact", version=1, pinned_hash=HASH)
    registry.get_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_storage_error_propagates():
    registry = AsyncMock()
    registry.get_content.side_effect = RuntimeError("storage failed")
    service = ArtifactShareContent(AsyncMock(), registry)
    service._authorization.authorize = AsyncMock(return_value=HASH)
    with pytest.raises(RuntimeError):
        await service.get_content(actor=ACTOR, artifact_id="artifact", version=1, pinned_hash=HASH)
