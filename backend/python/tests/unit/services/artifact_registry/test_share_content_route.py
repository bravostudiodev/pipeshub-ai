import hashlib
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connectors.api.artifacts_router import internal_share_content
from app.services.artifact_registry.access import ArtifactNotFoundError
from app.services.artifact_registry.deck_archive import DeckArchiveCache
from app.services.artifact_registry.models import Actor
from app.services.artifact_registry.share_content import ArtifactShareContent


def request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config_service=object()))
    )


@pytest.mark.asyncio
async def test_internal_content_uses_only_service_token_claims() -> None:
    claims = {
        "orgId": "org",
        "userId": "owner",
        "artifactId": "artifact",
        "version": 2,
        "contentHash": "a" * 64,
    }
    with patch("app.connectors.api.artifacts_router.ArtifactShareContent") as service:
        service.return_value.get_content = AsyncMock(return_value=b"pinned")
        response = await internal_share_content(request(), None, claims, AsyncMock())
    assert response.body == b"pinned"
    assert response.headers["cache-control"] == "no-store"
    service.return_value.get_content.assert_awaited_once_with(
        actor=Actor(org_id="org", user_id="owner"),
        artifact_id="artifact",
        version=2,
        pinned_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_presentation_preview_converts_only_verified_pinned_bytes() -> None:
    claims = {
        "orgId": "org", "userId": "owner", "artifactId": "artifact", "version": 2,
        "contentHash": "a" * 64, "name": "slides.pptx",
        "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    with (
        patch("app.connectors.api.artifacts_router.ArtifactShareContent") as service,
        patch("app.utils.libreoffice_convert.convert_with_libreoffice", new_callable=AsyncMock) as convert,
    ):
        service.return_value.get_content = AsyncMock(return_value=b"pinned pptx")
        convert.return_value = b"%PDF-1.4 converted"
        response = await internal_share_content(request(), None, claims, AsyncMock(), preview_pdf=True)
    service.return_value.get_content.assert_awaited_once_with(
        actor=Actor(org_id="org", user_id="owner"), artifact_id="artifact", version=2, pinned_hash="a" * 64
    )
    convert.assert_awaited_once_with(b"pinned pptx", "pptx", "pdf")
    assert response.body == b"%PDF-1.4 converted"
    assert response.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_shared_deck_cache_rechecks_authorization_before_cached_bytes() -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("dist/index.html", "<html></html>")
    content = archive.getvalue()
    content_hash = hashlib.sha256(content).hexdigest()
    authorization = AsyncMock(
        side_effect=[content_hash, ArtifactNotFoundError("revoked")]
    )
    registry = SimpleNamespace(get_content=AsyncMock(return_value=content))
    service = ArtifactShareContent(object(), registry)
    service._authorization.authorize = authorization
    args = {
        "actor": Actor(org_id="org", user_id="owner"),
        "artifact_id": "artifact",
        "version": 1,
        "pinned_hash": content_hash,
        "path": "index.html",
        "cache": DeckArchiveCache(),
    }

    assert (await service.get_deck_file(**args)).content.endswith(b"<html></html>")
    with pytest.raises(ArtifactNotFoundError):
        await service.get_deck_file(**args)
    assert authorization.await_count == 2
    registry.get_content.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"orgId": "org", "userId": "u", "artifactId": "a", "version": True},
        {"orgId": "org", "userId": "u", "artifactId": "a", "version": 0},
    ],
)
async def test_internal_content_rejects_missing_or_invalid_claims(
    claims: dict[str, object],
) -> None:
    with pytest.raises(HTTPException) as exc:
        await internal_share_content(request(), None, claims, AsyncMock())
    assert exc.value.status_code == 401
