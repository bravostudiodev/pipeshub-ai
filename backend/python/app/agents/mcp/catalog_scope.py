"""Authoritative, owner-bound identity for MCP catalog/session state."""

import copy
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from app.agents.constants.mcp_server_constants import (
    get_mcp_credentials_path,
    get_mcp_instance_path,
)
from app.agents.mcp.credential_lock import credential_refresh_lock
from app.agents.mcp.service import (
    SHARED_CREDENTIALS_UNSUPPORTED_MESSAGE,
    uses_shared_admin_credential,
)


class CatalogScopeError(Exception):
    """Safe-to-surface rejection of an ineligible MCP catalog scope."""


class LegacySharedAuthIneligible(CatalogScopeError):
    """A shared administrator credential: not used for any caller (AGENTS.md source authorization)."""


@dataclass(frozen=True)
class CatalogScope:
    instance: dict[str, Any] = field(repr=False)
    auth: dict[str, Any] = field(repr=False)
    instance_id: str
    org_id: str
    owner_id: str
    generation: str = field(repr=False)
    identity: str


def _stable_json(value: Any) -> bytes:  # noqa: ANN401
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()


def _scope_set(value: Any) -> Any:  # noqa: ANN401
    """A grant's scopes as a set: providers may reorder them on refresh without changing them."""
    if isinstance(value, str):
        return sorted(set(value.split()))
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return sorted(set(value))
    return value


def _scope_digest(
    instance: dict,
    auth: dict,
    instance_id: str,
    org_id: str,
    owner_id: str,
    generation: str,
) -> str:
    fields = (
        "name",
        "typeId",
        "useAdminAuth",
        "url",
        "transport",
        "command",
        "args",
        "requiredEnv",
        "optionalEnv",
        "env",
        "authMode",
        "updatedAt",
        "headerName",
        "scopes",
        "authorizationUrl",
        "tokenUrl",
        "connectTimeoutSeconds",
        "callTimeoutSeconds",
    )
    config = {key: instance.get(key) for key in fields}
    tokens = (
        auth.get("oauthTokens") if isinstance(auth.get("oauthTokens"), dict) else {}
    )
    permissions = {
        "declared": _scope_set(auth.get("scopes")),
        "legacyScope": _scope_set(auth.get("scope")),
        "tokenScope": _scope_set(tokens.get("scope")),
        "tokenScopes": _scope_set(tokens.get("scopes")),
    }
    material = _stable_json(
        {
            "v": 1,
            "org": org_id,
            "owner": owner_id,
            "instance": instance_id,
            "config": config,
            "permissions": permissions,
        }
    )
    key = (
        generation.encode()
        if instance.get("authMode") != "none"
        else b"oddjeeves-mcp-none-v1"
    )
    return "v1:" + hmac.new(key, material, hashlib.sha256).hexdigest()


def _validate_instance(
    instance: dict[str, Any], instance_id: str, org_id: str, owner_id: str
) -> str:
    if (
        not isinstance(instance, dict)
        or instance.get("_id") != instance_id
        or instance.get("orgId") != org_id
    ):
        raise CatalogScopeError("MCP instance is unavailable")
    if not org_id or not owner_id:
        raise CatalogScopeError("MCP identity is unavailable")
    mode = instance.get("authMode")
    if not isinstance(mode, str) or mode not in {"none", "oauth", "api_token", "headers"}:
        raise CatalogScopeError("MCP authorization is unavailable")
    return mode


def _validate(
    instance: dict[str, Any],
    auth: dict[str, Any] | None,
    instance_id: str,
    org_id: str,
    owner_id: str,
) -> dict[str, Any]:
    mode = _validate_instance(instance, instance_id, org_id, owner_id)
    if uses_shared_admin_credential(instance):
        raise LegacySharedAuthIneligible(SHARED_CREDENTIALS_UNSUPPORTED_MESSAGE)
    if mode == "none":
        return {}
    if not isinstance(auth, dict) or auth.get("isAuthenticated") is not True:
        raise CatalogScopeError("MCP authorization is unavailable")
    generation = auth.get("credentialGeneration")
    if generation is not None and (not isinstance(generation, str) or not generation):
        raise CatalogScopeError("MCP authorization is unavailable")
    if mode == "oauth":
        tokens = auth.get("oauthTokens")
        token = (tokens.get("accessToken") or tokens.get("access_token")) if isinstance(tokens, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise CatalogScopeError("MCP authorization is unavailable")
    else:
        credentials = auth.get("credentials")
        if not isinstance(credentials, dict):
            raise CatalogScopeError("MCP authorization is unavailable")
        if mode == "api_token":
            token = credentials.get("apiToken")
            has_token = isinstance(token, str) and bool(token.strip())
            env = credentials.get("env")
            allowed = set(instance.get("requiredEnv") or []) | set(instance.get("optionalEnv") or [])
            has_env = instance.get("transport") == "stdio" and isinstance(env, dict) and any(
                key in allowed and isinstance(value, str) and value.strip() for key, value in env.items()
            )
            if not has_token and not has_env:
                raise CatalogScopeError("MCP authorization is unavailable")
        else:
            header_name = credentials.get("headerName") or instance.get("headerName")
            header_value = credentials.get("headerValue")
            if not (isinstance(header_name, str) and header_name.strip()
                    and isinstance(header_value, str) and header_value.strip()):
                raise CatalogScopeError("MCP authorization is unavailable")
    return auth


async def load_catalog_scope(
    instance_id: str, org_id: str, owner_id: str, config_service: Any  # noqa: ANN401
) -> CatalogScope:
    if not instance_id or not org_id or not owner_id:
        raise CatalogScopeError("MCP identity is unavailable")
    instance_path = get_mcp_instance_path(instance_id)
    credential_path = get_mcp_credentials_path(instance_id, owner_id)
    for _ in range(3):
        raw_instance = await config_service.get_config(
            instance_path, default=None, use_cache=False, raise_on_error=True
        )
        instance = copy.deepcopy(raw_instance)
        if not isinstance(instance, dict):
            raise CatalogScopeError("MCP instance is unavailable")
        # Validate identity/configuration and shared-auth eligibility before any credential read.
        mode = _validate_instance(instance, instance_id, org_id, owner_id)
        if uses_shared_admin_credential(instance):
            raise LegacySharedAuthIneligible(SHARED_CREDENTIALS_UNSUPPORTED_MESSAGE)
        if mode == "none":
            auth = {}
            generation = "none"
            break
        raw_auth = await config_service.get_config(
            credential_path, default=None, use_cache=False, raise_on_error=True
        )
        auth = copy.deepcopy(raw_auth)
        _validate(instance, auth, instance_id, org_id, owner_id)
        generation = auth.get("credentialGeneration")
        if generation:
            break
        # Migration changes the refresh CAS snapshot. Serialize it with token
        # exchange so it cannot strand an already-rotated provider refresh token.
        async with credential_refresh_lock(instance_id, owner_id, config_service) as lease:
            latest_instance = await config_service.get_config(instance_path, default=None, use_cache=False, raise_on_error=True)
            latest_auth = await config_service.get_config(credential_path, default=None, use_cache=False, raise_on_error=True)
            if latest_instance != raw_instance or latest_auth != raw_auth:
                continue
            await lease.assert_owned()
            updated = copy.deepcopy(auth)
            updated["credentialGeneration"] = secrets.token_urlsafe(32)
            if await config_service.compare_and_set_config(credential_path, raw_auth, updated):
                auth = updated
                generation = updated["credentialGeneration"]
                break
        # A lost CAS may mean revoke/reconnect; reread both authority records.
    else:
        raise CatalogScopeError("MCP authorization changed during scope resolution")
    auth = copy.deepcopy(auth)
    identity = _scope_digest(instance, auth, instance_id, org_id, owner_id, generation)
    return CatalogScope(
        instance, auth, instance_id, org_id, owner_id, generation, identity
    )


async def scope_is_current(scope: CatalogScope, config_service: Any) -> bool:  # noqa: ANN401
    try:
        current = await load_catalog_scope(
            scope.instance_id, scope.org_id, scope.owner_id, config_service
        )
    except CatalogScopeError:
        return False
    return hmac.compare_digest(scope.identity, current.identity)
