import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.mcp.retrieval_trace import (
    discovery_fields,
    invocation_fields,
    record_event,
    redact_arguments,
    schema_fingerprint,
)


def _server(owner: str, access_token: str, scope: str = "channels:history") -> SimpleNamespace:
    return SimpleNamespace(
        instance_id="shared-instance",
        name="Slack",
        owner_id=owner,
        instance={"transport": "streamable_http", "authMode": "oauth", "url": "https://private.example/mcp"},
        auth={"isAuthenticated": True, "oauthTokens": {
            "accessToken": access_token, "scope": scope, "expiresIn": 3600,
            "createdAt": "2025-01-01T00:00:00+00:00",
        }},
    )


def test_redaction_keeps_structural_retrieval_args_and_drops_free_text_and_secrets() -> None:
    safe = redact_arguments({
        "channel_id": "C123",
        "limit": 5,
        "cursor": "opaque-cursor-2",
        "sort": "timestamp",
        "after": "2025-01-01",
        "query": "confidential raw Slack search terms",
        "search_text": "also confidential",
        "access_token": "do-not-store",
        "url": "https://private.example/path?secret=x",
        "surprise": "unknown free text",
        "filter": "search all channels for launch",
        "filters": {
            "field": "created_at", "operator": "gte", "value": "free text must not persist",
            "nested": {"query": "nested free text", "url": "https://private.example/x"},
        },
        "search_filter": "url https://private.example/private?q=query",
        "client_secret": "credential-like-secret",
        "refresh_token": "credential-like-refresh-token",
    })
    assert safe == {
        "channel_id": "C123", "limit": 5,
        "cursor": {"fingerprint": hashlib.sha256(b"opaque-cursor-2").hexdigest()},
        "sort": "timestamp", "after": "2025-01-01",
        "filters": {"field": "created_at", "operator": "gte"},
    }
    assert "confidential" not in repr(safe)
    assert "do-not-store" not in repr(safe)
    for forbidden in (
        "search all channels", "free text must not persist", "nested free text",
        "private.example", "credential-like-secret", "credential-like-refresh-token",
        "opaque-cursor-2",
    ):
        assert forbidden not in repr(safe)


def test_discovery_traces_are_separate_by_credential_owner_without_recording_credentials() -> None:
    tool = SimpleNamespace(namespaced_name="mcp_slack_search", input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}})
    alice = discovery_fields(_server("alice", "alice-secret"), [tool], None)
    bob = discovery_fields(_server("bob", "bob-secret", scope="channels:read"), [tool], None)

    assert alice["credentialOwnerId"] == "alice"
    assert bob["credentialOwnerId"] == "bob"
    assert alice["credentialExists"] and bob["credentialExists"]
    assert alice["credentialScopes"] == ["channels:history"]
    assert bob["credentialScopes"] == ["channels:read"]
    assert alice["credentialExpiresAt"] == "2025-01-01T01:00:00+00:00"
    assert alice["tools"] == bob["tools"]
    assert "alice-secret" not in repr(alice)
    assert "bob-secret" not in repr(bob)
    assert "private.example" not in repr(alice)


def test_schema_fingerprint_is_stable_and_distinguishes_schemas() -> None:
    schema = {"type": "object", "properties": {"limit": {"type": "integer"}}}
    assert schema_fingerprint(schema) == schema_fingerprint({"properties": schema["properties"], "type": "object"})
    assert schema_fingerprint(schema) != schema_fingerprint({"type": "object"})


def test_invocation_metadata_distinguishes_args_and_response_dates_without_content() -> None:
    server = _server("alice", "secret")
    fields = invocation_fields(
        server, "search", {"channel_id": "C1", "limit": 5, "query": "private phrase"}, 0,
        result={"messages": [
            {"channel_id": "C1", "ts": "2025-01-03", "text": "message secret"},
            {"channel_id": "C1", "ts": "2025-01-01", "text": "another secret"},
        ]},
    )
    assert fields["arguments"] == {"channel_id": "C1", "limit": 5}
    assert fields["response"]["resultCount"] == 2
    assert fields["response"]["oldestTimestamp"] == "2025-01-01"
    assert fields["response"]["newestTimestamp"] == "2025-01-03"
    assert "message secret" not in repr(fields)
    assert "private phrase" not in repr(fields)


@pytest.mark.asyncio
async def test_persisted_discovery_and_invocation_events_keep_each_callers_identity_separate() -> None:
    stored: dict[str, object] = {}

    async def set_config(key: str, value: object, *, ttl: int | None = None) -> bool:
        stored[key] = (value, ttl)
        return True

    service = SimpleNamespace(
        get_config=AsyncMock(return_value={"featureFlags": {"ENABLE_MCP_RETRIEVAL_TRACE": True}}),
        set_config=AsyncMock(side_effect=set_config),
    )
    contexts = [
        SimpleNamespace(config_service=service, tool_state={}, run_id=f"run-{caller}", conversation_id="conv-1",
                        user_id=effective, authenticated_user_id=caller, org_id="org-1")
        for caller, effective in (("alice", "alice"), ("bob", "agent-owner-bob"))
    ]
    for context, owner, channel in zip(contexts, ("alice", "agent-owner-bob"), ("C1", "C2")):
        await record_event(context, "discovery", {"instanceId": "shared", "credentialOwnerId": owner, "credentialExists": True})
        await record_event(context, "invocation", {
            "instanceId": "shared", "toolName": "search", "arguments": {"channel_id": channel, "limit": 5},
        })

    events = [value for value, _ttl in stored.values() if isinstance(value, dict) and "eventType" in value]
    assert all(ttl is not None and 0 < ttl <= 7 * 24 * 60 * 60 for _value, ttl in stored.values())
    assert len(events) == 4
    assert {event["userId"] for event in events if event["eventType"] == "discovery"} == {"alice", "bob"}
    assert {event["effectiveUserId"] for event in events} == {"alice", "agent-owner-bob"}
    assert {event["credentialOwnerId"] for event in events if event["eventType"] == "discovery"} == {"alice", "agent-owner-bob"}
    invocations = [event for event in events if event["eventType"] == "invocation"]
    assert {event["userId"] for event in invocations} == {"alice", "bob"}
    assert {event["arguments"]["channel_id"] for event in invocations} == {"C1", "C2"}
    assert len({event["traceId"] for event in events}) == 2
    assert {event["eventType"] for event in events} == {"discovery", "invocation"}
    assert all("accessToken" not in repr(event) for event in events)
