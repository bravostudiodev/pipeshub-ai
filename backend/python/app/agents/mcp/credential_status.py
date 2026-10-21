"""Marks a stored MCP credential as rejected so status reads stop saying "Connected".

Every path that learns a credential no longer works (tool discovery, a tool call, the
manual refresh route) calls `mark_reauth_required`, and every status read goes through
`resolve_effective_user_auth`, so the card, the model and the logs agree.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.constants.mcp_server_constants import get_mcp_credentials_path
from app.config.configuration_service import ConfigurationService
from app.utils.time_conversion import get_epoch_timestamp_in_ms

logger = logging.getLogger(__name__)

DEAUTH_REASON_CREDENTIAL_REJECTED = "credential_rejected"


async def mark_reauth_required(
    instance_id: str, owner_id: str, config_service: ConfigurationService, *, detail: str, source: str,
) -> bool:
    """Flip `isAuthenticated` off on the owner's own record. Returns False when there is
    no record to update (authMode none, or already disconnected)."""
    path = get_mcp_credentials_path(instance_id, owner_id)
    record = await config_service.get_config(path, default=None, use_cache=False)
    if not isinstance(record, dict) or not record.get("isAuthenticated"):
        return False
    record["isAuthenticated"] = False
    record["deauthReason"] = DEAUTH_REASON_CREDENTIAL_REJECTED
    record["deauthDetail"] = detail[:200]
    record["deauthSource"] = source
    record["deauthAt"] = get_epoch_timestamp_in_ms()
    await config_service.set_config(path, record)
    logger.warning(
        "MCP credential marked reauth_required: instance=%s owner=%s source=%s detail=%s",
        instance_id, owner_id, source, detail[:200],
    )
    return True


def reauth_status(auth: dict[str, Any] | None) -> tuple[bool, str | None]:
    """(needs_reauth, detail) for a resolved credential record."""
    if not isinstance(auth, dict) or auth.get("isAuthenticated"):
        return False, None
    if auth.get("deauthReason") != DEAUTH_REASON_CREDENTIAL_REJECTED:
        return False, None
    return True, auth.get("deauthDetail")
