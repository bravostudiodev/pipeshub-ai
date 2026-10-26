from typing import Any

import pytest

from app.agents.mcp.credential_status import mark_reauth_required, reauth_status


class _FakeConfig:
    def __init__(self, record: Any) -> None:
        self.store = {"/services/mcp/credentials/inst-1/user-1": record}

    async def get_config(self, key: str, default: Any = None, use_cache: bool = True, *, raise_on_error: bool = False) -> Any:
        return self.store.get(key, default)

    async def compare_and_set_config(self, key: str, expected: object, value: Any) -> bool:
        if self.store.get(key) != expected:
            return False
        self.store[key] = value
        return True


@pytest.mark.asyncio
async def test_mark_flips_only_an_authenticated_record() -> None:
    cfg = _FakeConfig({"isAuthenticated": True, "apiToken": "t"})
    assert await mark_reauth_required(
        "inst-1", "user-1", cfg, detail="401", source="discovery",
        expected_auth={"isAuthenticated": True, "apiToken": "t"},
    ) is True
    record = cfg.store["/services/mcp/credentials/inst-1/user-1"]
    assert record["isAuthenticated"] is False
    assert record["deauthSource"] == "discovery"
    assert record["apiToken"] == "t"  # the secret is kept so a reconnect can replace it, not lose it
    assert reauth_status(record) == (True, "401")


@pytest.mark.asyncio
async def test_mark_is_a_noop_without_a_live_record() -> None:
    cfg = _FakeConfig(None)
    assert await mark_reauth_required("inst-1", "user-1", cfg, detail="401", source="discovery") is False
    assert reauth_status(None) == (False, None)
    assert reauth_status({"isAuthenticated": False}) == (False, None)


def test_records_deauthenticated_by_the_older_refreshers_still_ask_for_reconnect() -> None:
    record = {"isAuthenticated": False, "deauthReason": "refresh_token_invalid"}
    assert reauth_status(record) == (True, "refresh token rejected")
