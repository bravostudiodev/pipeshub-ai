"""Authoritative Node conversation membership check for chat image analysis."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from app.config.constants.service import (
    DefaultEndpoints,
    TokenScopes,
    config_node_constants,
)
from app.utils.jwt import generate_jwt

if TYPE_CHECKING:
    from app.config.configuration_service import ConfigurationService


async def chat_image_is_member(
    config_service: ConfigurationService,
    org_id: str,
    user_id: str,
    conversation_id: str,
    virtual_record_id: str,
) -> bool:
    """Query Node using a narrowly scoped service token bound to caller identity.

    Missing configuration, malformed responses, non-success statuses and
    transport failures deny. Never consult request-supplied chat history.
    """
    try:
        endpoints = await config_service.get_config(config_node_constants.ENDPOINTS.value)
        if isinstance(endpoints, str):
            endpoints = json.loads(endpoints)
        node = ((endpoints or {}).get("nodejs") or {}).get("endpoint") or DefaultEndpoints.NODEJS_ENDPOINT.value
        token = await generate_jwt(config_service, {
            "orgId": org_id,
            "userId": user_id,
            "scopes": [TokenScopes.CONVERSATION_IMAGE_MEMBERSHIP.value],
        })
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            response = await client.post(
                f"{node.rstrip('/')}/api/v1/conversations/internal/image-attachment-membership",
                headers={"Authorization": f"Bearer {token}"},
                json={"conversationId": conversation_id, "virtualRecordId": virtual_record_id},
            )
        return response.status_code == 200 and response.json().get("allowed") is True
    except Exception:
        return False
