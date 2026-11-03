"""ACL and archive boundaries for private and shared Slidev file serving."""

import hashlib
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connectors.api.artifacts_router import (
    internal_artifact_deck_file,
    internal_share_content,
)
from app.services.artifact_registry.deck_archive import DeckArchiveCache, DeckFile
from app.services.artifact_registry.models import Actor


def request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config_service=object()))
    )


def deck_zip() -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("slides.md", "# title")
        archive.writestr("dist/index.html", "<html><head></head></html>")
        archive.writestr("dist/assets/theme.css", "body{color:red}")
    return result.getvalue()


@pytest.mark.asyncio
async def test_internal_preview_uses_capability_identity_and_exact_artifact_version() -> (
    None
):
    claims = {
        "orgId": "org-1",
        "userId": "user-1",
        "artifactId": "artifact-1",
        "version": 3,
        "name": "slidev-presentation.zip",
        "mimeType": "application/zip",
    }
    graph = object()
    with (
        patch("app.connectors.api.artifacts_router.ArtifactGalleryService") as gallery,
        patch(
            "app.services.artifact_registry.registry.ArtifactRegistryService"
        ) as registry,
        patch("app.modules.transformers.blob_storage.BlobStorage"),
        patch(
            "app.connectors.api.artifacts_router.deck_archive_cache", DeckArchiveCache()
        ),
    ):
        gallery.return_value.get = AsyncMock(
            return_value=SimpleNamespace(
                name="slidev-presentation.zip",
                mime_type="application/zip",
                versions=[
                    SimpleNamespace(
                        version=3, content_hash=hashlib.sha256(deck_zip()).hexdigest()
                    )
                ],
            )
        )
        registry.return_value.get_content = AsyncMock(return_value=deck_zip())
        response = await internal_artifact_deck_file(
            request(),
            "assets/theme.css",
            claims,
            graph,
        )
    assert response.body == b"body{color:red}"
    assert response.headers["content-type"].startswith("text/css")
    assert response.headers["access-control-allow-origin"] == "*"
    gallery.return_value.get.assert_awaited_once_with(
        Actor(org_id="org-1", user_id="user-1"), "artifact-1"
    )
    registry.return_value.get_content.assert_awaited_once_with(
        actor=Actor(org_id="org-1", user_id="user-1"),
        artifact_id="artifact-1",
        version=3,
    )


@pytest.mark.asyncio
async def test_private_preview_rechecks_acl_before_using_cached_files() -> None:
    from app.services.artifact_registry.access import ArtifactNotFoundError

    claims = {
        "orgId": "org-cache",
        "userId": "user-cache",
        "artifactId": "artifact-cache",
        "version": 3,
        "name": "slidev-presentation.zip",
        "mimeType": "application/zip",
    }
    detail = SimpleNamespace(
        name="slidev-presentation.zip",
        mime_type="application/zip",
        versions=[
            SimpleNamespace(
                version=3, content_hash=hashlib.sha256(deck_zip()).hexdigest()
            )
        ],
    )
    with (
        patch("app.connectors.api.artifacts_router.ArtifactGalleryService") as gallery,
        patch(
            "app.services.artifact_registry.registry.ArtifactRegistryService"
        ) as registry,
        patch("app.modules.transformers.blob_storage.BlobStorage"),
        patch(
            "app.connectors.api.artifacts_router.deck_archive_cache", DeckArchiveCache()
        ),
    ):
        gallery.return_value.get = AsyncMock(
            side_effect=[detail, ArtifactNotFoundError("revoked")]
        )
        registry.return_value.get_content = AsyncMock(return_value=deck_zip())
        first = await internal_artifact_deck_file(
            request(), "assets/theme.css", claims, object()
        )
        assert first.body == b"body{color:red}"
        with pytest.raises(HTTPException) as exc:
            await internal_artifact_deck_file(
                request(), "assets/theme.css", claims, object()
            )

    assert exc.value.status_code == 404
    registry.return_value.get_content.assert_awaited_once()
    assert gallery.return_value.get.await_count == 2


@pytest.mark.asyncio
async def test_private_preview_rejects_non_zip_artifact_before_reading_content() -> (
    None
):
    claims = {
        "orgId": "org-1",
        "userId": "user-1",
        "artifactId": "artifact-1",
        "version": 1,
        "name": "slidev-presentation.zip",
        "mimeType": "application/zip",
    }
    with (
        patch("app.connectors.api.artifacts_router.ArtifactGalleryService") as gallery,
        patch(
            "app.services.artifact_registry.registry.ArtifactRegistryService"
        ) as registry,
        patch("app.modules.transformers.blob_storage.BlobStorage"),
        patch(
            "app.connectors.api.artifacts_router.deck_archive_cache", DeckArchiveCache()
        ),
        pytest.raises(HTTPException) as exc,
    ):
        gallery.return_value.get = AsyncMock(
            return_value=SimpleNamespace(
                name="document.pdf", mime_type="application/pdf"
            )
        )
        await internal_artifact_deck_file(request(), "index.html", claims, object())
    assert exc.value.status_code == 404
    registry.return_value.get_content.assert_not_called()


@pytest.mark.asyncio
async def test_shared_preview_serves_only_validated_dist_file() -> None:
    claims = {
        "orgId": "org-1",
        "userId": "owner-1",
        "artifactId": "artifact-1",
        "version": 2,
        "contentHash": "a" * 64,
        "name": "slidev-presentation.zip",
        "mimeType": "application/zip",
    }
    with patch("app.connectors.api.artifacts_router.ArtifactShareContent") as share:
        share.return_value.get_deck_file = AsyncMock(
            return_value=DeckFile(b"body{color:red}", "text/css; charset=utf-8")
        )
        response = await internal_share_content(
            request(), "assets/theme.css", claims, object()
        )
    assert response.body == b"body{color:red}"
    assert response.headers["content-type"].startswith("text/css")


@pytest.mark.asyncio
async def test_shared_preview_rejects_source_and_traversal_paths() -> None:
    claims = {
        "orgId": "org-1",
        "userId": "owner-1",
        "artifactId": "artifact-1",
        "version": 2,
        "contentHash": "a" * 64,
        "name": "slidev-presentation.zip",
        "mimeType": "application/zip",
    }
    from app.services.artifact_registry.access import ArtifactNotFoundError

    with patch("app.connectors.api.artifacts_router.ArtifactShareContent") as share:
        share.return_value.get_deck_file = AsyncMock(
            side_effect=ArtifactNotFoundError("unavailable")
        )
        for requested_path in ("slides.md", "../slides.md", "assets/missing.css"):
            with pytest.raises(HTTPException) as exc:
                await internal_share_content(
                    request(), requested_path, claims, object()
                )
            assert exc.value.status_code == 404
