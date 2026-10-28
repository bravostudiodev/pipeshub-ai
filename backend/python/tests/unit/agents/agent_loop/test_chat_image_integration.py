import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.agents.agent_loop import image_analysis_provider, image_analysis_resolver
from app.agents.agent_loop.analyze_image_tool import AnalyzeImageTool
from app.agents.agent_loop.image_attachment_references import (
    image_attachment_references,
)


def test_current_and_history_image_ids_are_exposed_as_text() -> None:
    ctx = SimpleNamespace(
        previous_conversations=[{"role": "user_query", "attachments": [
            {"mimeType": "image/png", "virtualRecordId": "old", "recordName": "old.png"},
        ]}],
        tool_state={"attachments": [{"mimeType": "image/jpeg", "virtualRecordId": "new", "recordName": "new.jpg"}]},
    )
    assert image_attachment_references(ctx) == [{"id": "old", "name": "old.png"}, {"id": "new", "name": "new.jpg"}]


@pytest.mark.asyncio
async def test_tool_resolves_and_hands_stored_image_to_vision(monkeypatch) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    blob = SimpleNamespace(get_record_from_storage=AsyncMock(return_value={
        "block_containers": {"blocks": [{"type": "image", "data": {"uri": uri}}]},
    }))
    ctx = SimpleNamespace(authenticated_user_id="caller", org_id="org", conversation_id="chat",
                          graph_provider=object(), blob_store=blob, config_service=object())
    monkeypatch.setattr(image_analysis_resolver, "caller_can_read_virtual_record", AsyncMock(return_value=True))
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="A red image.")))
    monkeypatch.setattr(image_analysis_provider, "_get_image_analysis_model", AsyncMock(return_value=(model, {"isMultimodal": True})))
    result = await AnalyzeImageTool(ctx, AsyncMock(return_value=True)).execute("ref")
    assert result.success and result.data == "A red image."
    assert model.ainvoke.await_args.args[0][0].content[1]["image_url"]["url"] == uri


@pytest.mark.asyncio
async def test_cross_user_image_never_reaches_storage_or_vision(monkeypatch) -> None:
    blob = SimpleNamespace(get_record_from_storage=AsyncMock())
    ctx = SimpleNamespace(authenticated_user_id="caller", org_id="org", conversation_id="chat",
                          graph_provider=object(), blob_store=blob, config_service=object())
    acl = AsyncMock(return_value=True)
    monkeypatch.setattr(image_analysis_resolver, "caller_can_read_virtual_record", acl)
    provider = AsyncMock()
    monkeypatch.setattr(image_analysis_provider, "_get_image_analysis_model", provider)
    result = await AnalyzeImageTool(ctx, AsyncMock(return_value=False)).execute("other-users-image")
    assert not result.success
    acl.assert_not_awaited()
    blob.get_record_from_storage.assert_not_awaited()
    provider.assert_not_awaited()
