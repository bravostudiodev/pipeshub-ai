from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.artifact_registry.access import AccessDeniedError, ArtifactNotFoundError
from app.services.artifact_registry.models import Actor
from app.services.artifact_registry.share_authorization import ArtifactShareAuthorization

from .fakes import FakeGraphProvider


@pytest.fixture
def policy():
    result = ArtifactShareAuthorization(AsyncMock())
    result._graph.get_document = AsyncMock(return_value={"visibility": "VISIBLE"})
    result._access.authorize_write = AsyncMock(return_value={})
    result._gallery.get = AsyncMock(return_value=SimpleNamespace(
        versions=[SimpleNamespace(version=1, content_hash="a" * 64), SimpleNamespace(version=2, content_hash="b" * 64)]
    ))
    return result


@pytest.mark.asyncio
async def test_owner_can_publish_selected_version(policy):
    actor = Actor(org_id="org", user_id="owner")
    await policy.authorize(actor, "artifact", 1)
    policy._access.authorize_write.assert_awaited_once_with(actor, "artifact")
    policy._gallery.get.assert_awaited_once_with(actor, "artifact")


@pytest.mark.asyncio
async def test_reader_is_denied_before_gallery_lookup(policy):
    policy._access.authorize_write.side_effect = AccessDeniedError("not owner")
    with pytest.raises(ArtifactNotFoundError):
        await policy.authorize(Actor(org_id="org", user_id="reader"), "artifact", 1)
    policy._gallery.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [0, -1, True, 3])
async def test_invalid_or_missing_version_denied(policy, version):
    with pytest.raises(ArtifactNotFoundError):
        await policy.authorize(Actor(org_id="org", user_id="owner"), "artifact", version)


@pytest.mark.asyncio
async def test_missing_content_hash_fails_closed(policy):
    policy._gallery.get.return_value.versions[0].content_hash = ""
    with pytest.raises(ArtifactNotFoundError):
        await policy.authorize(Actor(org_id="org", user_id="owner"), "artifact", 1)


@pytest.mark.asyncio
async def test_hidden_artifact_denied(policy):
    policy._graph.get_document.return_value = {"visibility": "STAGING"}
    with pytest.raises(ArtifactNotFoundError):
        await policy.authorize(Actor(org_id="org", user_id="owner"), "artifact", 1)
    policy._gallery.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("user,org,role", [
    ("reader", "org", "READER"),
    ("other", "org", None),
    ("owner", "other-org", "OWNER"),
])
async def test_real_access_policy_denies_reader_other_user_and_org(user, org, role):
    graph = FakeGraphProvider()
    graph.add_user(user, key="user-key")
    graph.nodes["records"]["artifact"] = {"_key": "artifact", "orgId": "org"}
    if role:
        graph.edges["permission"].append({"from_id": "user-key", "to_id": "artifact", "role": role})
    policy = ArtifactShareAuthorization(graph)
    with pytest.raises(ArtifactNotFoundError):
        await policy.authorize(Actor(org_id=org, user_id=user), "artifact", 1)


@pytest.mark.asyncio
async def test_visibility_or_storage_failure_fails_closed(policy):
    policy._gallery.get.side_effect = RuntimeError("graph unavailable")
    with pytest.raises(RuntimeError):
        await policy.authorize(Actor(org_id="org", user_id="owner"), "artifact", 1)
