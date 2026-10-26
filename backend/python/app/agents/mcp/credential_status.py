"""Persist a permanent provider rejection only while the saved grant still matches."""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from app.agents.constants.mcp_server_constants import get_mcp_credentials_path
from app.config.configuration_service import ConfigurationService
from app.utils.time_conversion import get_epoch_timestamp_in_ms

logger = logging.getLogger(__name__)

DEAUTH_REASON_CREDENTIAL_REJECTED = "credential_rejected"
# Written by the background refreshers before `credential_rejected` existed, and still by the
# toolset refresher: both mean the provider rejected the saved grant.
_REJECTED_REASONS = frozenset({DEAUTH_REASON_CREDENTIAL_REJECTED, "refresh_token_invalid"})


async def mark_reauth_required(
    instance_id: str, owner_id: str, config_service: ConfigurationService, *, detail: str, source: str,
    expected_auth: dict[str, Any] | None = None,
) -> bool:
    """Mark only the credential snapshot permanently rejected by the provider.

    The conditional write prevents disconnect/reconnect from being overwritten
    even when it happens after the snapshot check.
    """
    if expected_auth is None:
        return False
    path = get_mcp_credentials_path(instance_id, owner_id)
    record = await config_service.get_config(path, default=None, use_cache=False, raise_on_error=True)
    if not isinstance(record, dict) or not record.get("isAuthenticated") or record != expected_auth:
        return False
    record = deepcopy(record)
    record["isAuthenticated"] = False
    record["deauthReason"] = DEAUTH_REASON_CREDENTIAL_REJECTED
    record["deauthDetail"] = detail[:200]
    record["deauthSource"] = source
    record["deauthAt"] = get_epoch_timestamp_in_ms()
    if not await config_service.compare_and_set_config(path, expected_auth, record):
        return False
    logger.warning(
        "MCP credential marked reauth_required: instance=%s owner=%s source=%s detail=%s",
        instance_id, owner_id, source, detail[:200],
    )
    return True


def reauth_status(auth: dict[str, Any] | None) -> tuple[bool, str | None]:
    """(needs_reauth, detail) for a resolved credential record."""
    if not isinstance(auth, dict) or auth.get("isAuthenticated"):
        return False, None
    if auth.get("deauthReason") not in _REJECTED_REASONS:
        return False, None
    return True, auth.get("deauthDetail") or "refresh token rejected"
