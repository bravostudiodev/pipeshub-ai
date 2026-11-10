"""Fail-closed loading of chat images for vision analysis.

The membership checker must consult authoritative server-side conversation
records. Request-supplied attachment lists are not an authority. This module
is not wired into chat until such a checker is available for that entry point.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.agents.agent_loop.image_analysis_input import (
    validate_stored_image_data_uri,
)
from app.utils.record_access import caller_can_read_virtual_record

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext

logger = logging.getLogger(__name__)

# Arguments are authenticated org, authenticated user, conversation, record.
MembershipCheck = Callable[[str, str, str, str], Awaitable[bool]]


class ImageAttachmentUnavailable(Exception):
    """The image is missing, inaccessible, or cannot be safely loaded."""


async def resolve_chat_image(
    context: AgentContext,
    virtual_record_id: str,
    membership_check: MembershipCheck | None,
) -> str:
    """Return one validated stored image, never fetching a model-provided URL."""
    user_id = context.authenticated_user_id
    org_id = context.org_id
    conversation_id = context.conversation_id
    if not all((user_id, org_id, conversation_id, virtual_record_id, membership_check,
                context.graph_provider, context.blob_store)):
        raise ImageAttachmentUnavailable("Image attachment is unavailable")
    try:
        # Do not use the resolver's explicit service-account fallback. The
        # graph ACL implementation may itself recognize organization grants;
        # authoritative conversation membership remains mandatory.
        if not await membership_check(org_id, user_id, conversation_id, virtual_record_id):
            raise ImageAttachmentUnavailable("Image attachment is unavailable")
        if not await caller_can_read_virtual_record(
            context.graph_provider, user_id=user_id, org_id=org_id,
            virtual_record_id=virtual_record_id, logger=logger,
            is_service_account=False,
        ):
            raise ImageAttachmentUnavailable("Image attachment is unavailable")
        record = await context.blob_store.get_record_from_storage(
            virtual_record_id=virtual_record_id, org_id=org_id,
        )
        if not isinstance(record, dict):
            raise ImageAttachmentUnavailable("Image attachment is unavailable")
        container = record.get("block_containers")
        blocks = container.get("blocks", []) if isinstance(container, dict) else record.get("blocks", [])
        images: list[Any] = [
            block.get("data", {}).get("uri")
            for block in blocks or []
            if isinstance(block, dict) and block.get("type") == "image"
            and isinstance(block.get("data"), dict)
        ]
        if len(images) != 1:
            raise ImageAttachmentUnavailable("Image attachment is unavailable")
        return validate_stored_image_data_uri(images[0])
    except ImageAttachmentUnavailable:
        raise
    except Exception as exc:
        raise ImageAttachmentUnavailable("Image attachment is unavailable") from exc
