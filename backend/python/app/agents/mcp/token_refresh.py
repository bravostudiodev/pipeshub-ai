"""Shared, user-bound OAuth refresh for background, manual and chat callers."""
from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.agents.constants.mcp_server_constants import (
    get_mcp_credentials_path,
    get_mcp_dcr_client_path,
    get_mcp_oauth_client_config_path,
    get_mcp_shared_dcr_client_path,
)
from app.agents.mcp import oauth_client as oauth_client_module
from app.agents.mcp.credential_lock import credential_refresh_lock
from app.agents.mcp.models import OAuthTokens
from app.utils.time_conversion import get_epoch_timestamp_in_ms

if TYPE_CHECKING:
    from app.agents.mcp.credential_lock import RefreshLease
    from app.config.configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

__all__ = [
    "MCPTokenRefreshError", "MCPTokenRefreshTransientError",
    "resolve_client_credentials", "refresh_credential_record",
]

_refresh_locks: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
REFRESH_REQUEST_MAX_SECONDS = 20.0
LOCAL_LOCK_WAIT_SECONDS = 25.0
PREVIOUS_CLIENT_FIELD = "previousClient"
# Saving a rotated grant is retried with these waits, all inside the 60 s refresh lease
# (the provider call itself is capped at 20 s).
_SAVE_RETRY_WAITS_SECONDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


@dataclass(frozen=True)
class _UnsavedRotation:
    """Tokens a provider issued that could not be saved. The provider has usually already
    invalidated `replaced_refresh_token`, so refreshing with it again would sign the user out."""

    replaced_refresh_token: str
    credential_generation: str | None
    replaced_oauth_tokens: dict[str, Any]
    tokens: OAuthTokens


# Per (instance, owner), process-local: the next refresh in this process saves these first.
_unsaved_rotations: dict[tuple[str, str], _UnsavedRotation] = {}
_inflight_refreshes: set[asyncio.Task[OAuthTokens]] = set()


class MCPTokenRefreshError(ValueError):
    """The saved grant is missing, revoked, or lacks required refresh configuration."""


class MCPTokenRefreshTransientError(MCPTokenRefreshError):
    """Infrastructure/lease/persistence failure, not a rejected user credential."""


def _registered_clients(record: object) -> list[dict[str, Any]]:
    if not isinstance(record, dict) or not record.get("clientId"):
        return []
    previous = record.get(PREVIOUS_CLIENT_FIELD)
    return [record, previous] if isinstance(previous, dict) and previous.get("clientId") else [record]


async def resolve_client_credentials(
    instance_id: str, owner_id: str, config_service: ConfigurationService, *, issued_by: str | None = None,
) -> tuple[str | None, str | None]:
    """Match the issuing client; legacy grants retain their previous resolution order."""
    for path in (
        get_mcp_dcr_client_path(instance_id, owner_id),
        get_mcp_shared_dcr_client_path(instance_id),
        get_mcp_oauth_client_config_path(instance_id),
    ):
        record = await config_service.get_config(path, default=None, use_cache=False, raise_on_error=True)
        clients = _registered_clients(record)
        if issued_by is None and clients:
            return clients[0]["clientId"], clients[0].get("clientSecret")
        for client in clients:
            if client["clientId"] == issued_by:
                return client["clientId"], client.get("clientSecret")
    return None, None


async def refresh_credential_record(
    instance_id: str, owner_id: str, config_service: ConfigurationService, *, stale_access_token: str | None = None,
) -> OAuthTokens:
    """Refresh under a shared lease; reuse a grant already refreshed by another caller.

    Cancellation of chat/discovery must not abandon saving a rotated refresh token.
    Only the bounded provider operation and conditional persistence continue; the
    cancelled caller is not resumed and a disconnected grant cannot be restored.
    """
    task = asyncio.create_task(_refresh_under_locks(instance_id, owner_id, config_service, stale_access_token))
    # The event loop holds tasks weakly; a refresh outliving its cancelled caller needs this.
    _inflight_refreshes.add(task)
    task.add_done_callback(_inflight_refreshes.discard)
    task.add_done_callback(_observe_refresh_failure)
    return await asyncio.shield(task)


def _observe_refresh_failure(task: asyncio.Task[OAuthTokens]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.debug("MCP refresh task failed (%s)", type(task.exception()).__name__)


async def _refresh_under_locks(
    instance_id: str, owner_id: str, config_service: ConfigurationService, stale_access_token: str | None,
) -> OAuthTokens:
    try:
        local_lock = _refresh_locks[(instance_id, owner_id)]
        await asyncio.wait_for(local_lock.acquire(), timeout=LOCAL_LOCK_WAIT_SECONDS)
        try:
            async with credential_refresh_lock(instance_id, owner_id, config_service) as lease:
                return await _refresh_credential_record_locked(instance_id, owner_id, config_service, stale_access_token, lease)
        finally:
            local_lock.release()
    except (MCPTokenRefreshError, oauth_client_module.MCPOAuthError):
        raise
    except Exception as exc:
        raise MCPTokenRefreshTransientError("Could not refresh this connection right now. Please try again shortly.") from exc


def _tokens_from_record(record: object) -> OAuthTokens:
    if not isinstance(record, dict) or record.get("isAuthenticated") is False:
        raise MCPTokenRefreshError("The connection was disconnected or is no longer authorized")
    tokens = record.get("oauthTokens")
    if not isinstance(tokens, dict):
        raise MCPTokenRefreshError("Invalid OAuth token record; reconnect is required")
    try:
        return OAuthTokens.model_validate(tokens)
    except ValidationError as exc:
        # A stored record that can't be read won't become readable by retrying.
        raise MCPTokenRefreshError("Invalid OAuth token record; reconnect is required") from exc


async def _refresh_credential_record_locked(
    instance_id: str, owner_id: str, config_service: ConfigurationService, stale_access_token: str | None,
    lease: RefreshLease,
) -> OAuthTokens:
    cred_path = get_mcp_credentials_path(instance_id, owner_id)
    record = await config_service.get_config(cred_path, default=None, use_cache=False, raise_on_error=True)
    if not isinstance(record, dict):
        raise MCPTokenRefreshError("No MCP credential record found")
    record = deepcopy(record)
    if record.get("isAuthenticated") is False:
        raise MCPTokenRefreshError("The connection was disconnected or is no longer authorized")
    if not record.get("credentialGeneration"):
        # Catalog migration uses the same lease. Persist the legacy generation
        # before a provider can invalidate the refresh token through rotation.
        for _ in range(3):
            _tokens_from_record(record)
            await lease.assert_owned()
            updated = {**record, "credentialGeneration": secrets.token_urlsafe(32)}
            if await config_service.compare_and_set_config(cred_path, record, updated):
                record = updated
                break
            current = await config_service.get_config(cred_path, default=None, use_cache=False, raise_on_error=True)
            _tokens_from_record(current)
            if (current.get("credentialGeneration") or current.get("oauthTokens") != record.get("oauthTokens")):
                return _tokens_from_record(current)
            record = deepcopy(current)
        else:
            raise MCPTokenRefreshTransientError("Could not prepare this connection for refresh. Please try again shortly.")
    tokens_dict = record.get("oauthTokens") or {}
    if not isinstance(tokens_dict, dict):
        raise MCPTokenRefreshError("Invalid OAuth token record; reconnect is required")
    stored_access_token = tokens_dict.get("accessToken") or tokens_dict.get("access_token")
    if stale_access_token and stored_access_token and stored_access_token != stale_access_token:
        return _tokens_from_record(record)
    refresh_token = tokens_dict.get("refreshToken") or tokens_dict.get("refresh_token")
    parked = _unsaved_rotations.pop((instance_id, owner_id), None)
    if parked is not None:
        if (
            parked.replaced_refresh_token != refresh_token
            or parked.credential_generation != record.get("credentialGeneration")
            or parked.replaced_oauth_tokens != record.get("oauthTokens")
        ):
            # A reconnect or a sibling refresh took precedence over this unsaved rotation.
            return _tokens_from_record(record)
        # Save the grant first; its access token may be old, so refresh with it right after.
        logger.warning("Saving MCP tokens a provider issued earlier that could not be saved then")
        await _save_refreshed_record(
            config_service, cred_path, record, parked.tokens, lease, key=(instance_id, owner_id),
            replaced_refresh_token=refresh_token,
        )
        record = await config_service.get_config(cred_path, default=None, use_cache=False, raise_on_error=True)
        _tokens_from_record(record)
        record = deepcopy(record)
        tokens_dict = record.get("oauthTokens") or {}
        refresh_token = tokens_dict.get("refreshToken") or tokens_dict.get("refresh_token")
    if not refresh_token:
        raise MCPTokenRefreshError("No refresh token available; reconnect is required")
    token_url = tokens_dict.get("tokenUrl") or tokens_dict.get("token_url")
    if not token_url:
        raise MCPTokenRefreshError("No tokenUrl persisted; reconnect is required")
    client_id, client_secret = await resolve_client_credentials(
        instance_id, owner_id, config_service, issued_by=tokens_dict.get("clientId") or tokens_dict.get("client_id"),
    )
    if not client_id:
        raise MCPTokenRefreshError("No matching OAuth client configuration found for this grant")
    await lease.assert_owned()
    try:
        async with asyncio.timeout(REFRESH_REQUEST_MAX_SECONDS):
            new_tokens = await oauth_client_module.refresh_access_token(
                token_url=token_url, client_id=client_id, client_secret=client_secret, refresh_token=refresh_token,
            )
    except oauth_client_module.MCPRefreshTokenInvalidError as exc:
        await lease.assert_owned()
        current = await config_service.get_config(cred_path, default=None, use_cache=False, raise_on_error=True)
        if current != record:
            _tokens_from_record(current)
            if (
                current.get("oauthTokens") != record.get("oauthTokens")
                or current.get("credentialGeneration") != record.get("credentialGeneration")
            ):
                return _tokens_from_record(current)
        exc.rejected_auth = deepcopy(current)
        raise
    # RFC 6749 permits omitting an unchanged scope on refresh. Do not turn
    # ordinary token rotation into a catalog permission-generation change.
    scope = new_tokens.scope if new_tokens.scope is not None else tokens_dict.get("scope")
    new_tokens = new_tokens.model_copy(update={"client_id": client_id, "scope": scope})
    return await _save_refreshed_record(
        config_service, cred_path, record, new_tokens, lease, key=(instance_id, owner_id),
        replaced_refresh_token=refresh_token,
    )


async def _save_refreshed_record(
    config_service: ConfigurationService, cred_path: str, expected: dict[str, Any], tokens: OAuthTokens,
    lease: RefreshLease, *, key: tuple[str, str], replaced_refresh_token: str,
) -> OAuthTokens:
    attempts = len(_SAVE_RETRY_WAITS_SECONDS) + 1
    original_generation = expected.get("credentialGeneration")
    original_oauth_tokens = deepcopy(expected.get("oauthTokens"))

    def park_rotation() -> None:
        _unsaved_rotations[key] = _UnsavedRotation(
            replaced_refresh_token, original_generation, original_oauth_tokens, tokens,
        )

    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(_SAVE_RETRY_WAITS_SECONDS[attempt - 1])
        try:
            await lease.assert_owned()
        except Exception:
            # The provider has already issued a possibly single-use rotation. Never write
            # without a verified lease; a later refresh can safely recover it under a new one.
            park_rotation()
            raise
        updated = {**expected, "oauthTokens": tokens.model_dump(by_alias=True, mode="json"), "updatedAt": get_epoch_timestamp_in_ms()}
        try:
            if await config_service.compare_and_set_config(cred_path, expected, updated):
                return tokens
            current = await config_service.get_config(cred_path, default=None, use_cache=False, raise_on_error=True)
        except Exception as exc:
            logger.warning("Saving refreshed MCP tokens failed (attempt=%d, error_type=%s)", attempt + 1, type(exc).__name__)
            continue
        current_tokens = _tokens_from_record(current)
        if current.get("oauthTokens") != expected.get("oauthTokens"):
            return current_tokens
        if current.get("credentialGeneration") != expected.get("credentialGeneration"):
            return current_tokens
        # Metadata changed, but not the grant: retain it in the conditional retry.
        expected = deepcopy(current)
    park_rotation()
    logger.error("Refreshed MCP tokens could not be saved after %d attempts; they are kept for the next refresh", attempts)
    raise MCPTokenRefreshTransientError("Could not save the refreshed connection. Please try again shortly.")
