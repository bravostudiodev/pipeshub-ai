"""User-facing artifact gallery HTTP routes (connectors service)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.middlewares.auth import require_scopes, require_service_token
from app.config.constants.http_status_code import HttpStatusCode
from app.config.constants.service import OAuthScopes, TokenScopes
from app.services.artifact_registry.access import ArtifactNotFoundError
from app.services.artifact_registry.gallery import ArtifactGalleryService, ArtifactListQuery
from app.services.artifact_registry.models import Actor
from app.services.artifact_registry.share_authorization import ArtifactShareAuthorization
from app.services.artifact_registry.share_content import ArtifactShareContent
from app.services.graph_db.interface.graph_db_provider import IGraphDBProvider

logger = logging.getLogger(__name__)

artifacts_router = APIRouter(tags=["Artifacts"])


async def get_graph_provider(request: Request) -> IGraphDBProvider:
    return request.app.state.graph_provider


def _parse_comma_separated_str(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _actor_from_request(request: Request) -> Actor:
    user = getattr(request.state, "user", None) or {}
    user_id = user.get("userId")
    org_id = user.get("orgId")
    if not user_id or not org_id:
        raise HTTPException(
            status_code=HttpStatusCode.UNAUTHORIZED.value,
            detail="Authentication required",
        )
    return Actor(org_id=org_id, user_id=user_id)


@artifacts_router.get("/api/v1/internal/artifact-share/content")
async def internal_share_content(
    request: Request,
    claims: Mapping[str, Any] = Depends(require_service_token(TokenScopes.ARTIFACT_SHARE_CONTENT)),
    graph_provider: IGraphDBProvider = Depends(get_graph_provider),
) -> Response:
    """Only a service token can name the owner, artifact and pinned version.

    The Node caller must validate the share and active owner on each request.
    This endpoint independently checks owner permission and visibility.
    """
    org_id, user_id, artifact_id, version, content_hash = (
        claims.get("orgId"), claims.get("userId"), claims.get("artifactId"), claims.get("version"), claims.get("contentHash")
    )
    if not all(isinstance(v, str) and v for v in (org_id, user_id, artifact_id)):
        raise HTTPException(status_code=401, detail="Invalid service token")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise HTTPException(status_code=401, detail="Invalid service token")
    if not isinstance(content_hash, str) or len(content_hash) != 64:
        raise HTTPException(status_code=401, detail="Invalid service token")
    from app.modules.transformers.blob_storage import BlobStorage
    from app.services.artifact_registry.registry import ArtifactRegistryService

    registry = ArtifactRegistryService(graph_provider, BlobStorage(logger, request.app.state.config_service))
    try:
        content = await ArtifactShareContent(graph_provider, registry).get_content(
            actor=Actor(org_id=org_id, user_id=user_id), artifact_id=artifact_id, version=version,
            pinned_hash=content_hash,
        )
    except ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact unavailable") from None
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@artifacts_router.get(
    "/api/v1/artifacts",
    dependencies=[Depends(require_scopes(OAuthScopes.CONNECTOR_READ, OAuthScopes.KB_READ))],
)
async def list_artifacts_gallery(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str | None = None,
    artifact_types: str | None = Query(None, description="Comma-separated artifact types"),
    conversation_id: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    sort_by: str = "createdAtTimestamp",
    sort_order: str = "desc",
    graph_provider: IGraphDBProvider = Depends(get_graph_provider),
) -> dict:
    actor = _actor_from_request(request)
    gallery = ArtifactGalleryService(graph_provider)
    query = ArtifactListQuery(
        search=search,
        page=page,
        limit=limit,
        artifact_types=_parse_comma_separated_str(artifact_types),
        conversation_id=conversation_id,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    try:
        result = await gallery.list(actor, query)
    except ArtifactNotFoundError as e:
        raise HTTPException(status_code=HttpStatusCode.NOT_FOUND.value, detail=str(e)) from e
    return {
        "items": [item.model_dump(by_alias=True) for item in result.items],
        "pagination": {
            "page": result.page,
            "limit": result.limit,
            "totalCount": result.total_count,
            "totalPages": result.total_pages,
        },
    }


@artifacts_router.get(
    "/api/v1/artifacts/{artifact_id}",
    dependencies=[Depends(require_scopes(OAuthScopes.CONNECTOR_READ, OAuthScopes.KB_READ))],
)
async def get_artifact_gallery(
    request: Request,
    artifact_id: str,
    graph_provider: IGraphDBProvider = Depends(get_graph_provider),
) -> dict:
    actor = _actor_from_request(request)
    gallery = ArtifactGalleryService(graph_provider)
    try:
        detail = await gallery.get(actor, artifact_id)
    except ArtifactNotFoundError:
        raise HTTPException(
            status_code=HttpStatusCode.NOT_FOUND.value,
            detail="Artifact not found",
        ) from None
    return detail.model_dump(by_alias=True)


@artifacts_router.post(
    "/api/v1/artifacts/{artifact_id}/share-authorization",
    dependencies=[Depends(require_scopes(OAuthScopes.CONNECTOR_READ, OAuthScopes.KB_READ))],
)
async def authorize_artifact_share(
    request: Request,
    artifact_id: str,
    version: int = Query(..., ge=1),
    graph_provider: IGraphDBProvider = Depends(get_graph_provider),
) -> dict:
    """Check the authenticated caller's authority; this does not create a link."""
    actor = _actor_from_request(request)
    try:
        content_hash = await ArtifactShareAuthorization(graph_provider).authorize(actor, artifact_id, version)
        detail = await ArtifactGalleryService(graph_provider).get(actor, artifact_id)
    except ArtifactNotFoundError:
        raise HTTPException(
            status_code=HttpStatusCode.NOT_FOUND.value,
            detail="Artifact or version not found",
        ) from None
    return {"authorized": True, "contentHash": content_hash, "name": detail.name, "mimeType": detail.mime_type}


@artifacts_router.get(
    "/api/v1/artifacts/{artifact_id}/versions",
    dependencies=[Depends(require_scopes(OAuthScopes.CONNECTOR_READ, OAuthScopes.KB_READ))],
)
async def list_artifact_versions(
    request: Request,
    artifact_id: str,
    graph_provider: IGraphDBProvider = Depends(get_graph_provider),
) -> dict:
    actor = _actor_from_request(request)
    gallery = ArtifactGalleryService(graph_provider)
    try:
        versions = await gallery.list_versions(actor, artifact_id)
    except ArtifactNotFoundError:
        raise HTTPException(
            status_code=HttpStatusCode.NOT_FOUND.value,
            detail="Artifact not found",
        ) from None
    return {"versions": [v.model_dump(by_alias=True) for v in versions]}
