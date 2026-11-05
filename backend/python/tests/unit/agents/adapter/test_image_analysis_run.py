"""Scripted text-model run through the real image tool and provider handoff."""
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from app.agent_loop_lib.agent import Agent
from app.agent_loop_lib.agent.loops import ReActLoop
from app.agent_loop_lib.agent.spec import AgentSpec, ModelSpec
from app.agent_loop_lib.core.messages import ToolCall
from app.agent_loop_lib.core.types import Goal
from app.agent_loop_lib.runtime.runtime import AgentRuntime
from app.agent_loop_lib.tools.registry import ToolRegistry
from app.agent_loop_lib.transport.registry import TransportRegistry
from app.agents.agent_loop import image_analysis_provider, image_analysis_resolver
from app.agents.agent_loop.analyze_image_tool import AnalyzeImageTool
from app.agents.agent_loop.factory import PipesHubAgentFactory
from tests.unit.agents.adapter.conftest import make_context
from tests.unit.agents.adapter.support.scripted_transport import ScriptedTransport


async def test_text_model_calls_vision_tool_and_receives_findings(monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    context = make_context(authenticated_user_id="caller", conversation_id="chat")
    context.blob_store.get_record_from_storage = AsyncMock(return_value={
        "block_containers": {"blocks": [{"type": "image", "data": {"uri": uri}}]},
    })
    monkeypatch.setattr(image_analysis_resolver, "caller_can_read_virtual_record", AsyncMock(return_value=True))
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="A red square.")))
    monkeypatch.setattr(image_analysis_provider, "_get_image_analysis_model", AsyncMock(return_value=(model, {"isMultimodal": True})))
    checker = AsyncMock(return_value=True)
    tools = ToolRegistry()
    tools.register_tool(AnalyzeImageTool(context, checker))
    transport = ScriptedTransport()
    transport.add_tool_call(ToolCall(id="call-1", name="analyze_image", arguments={
        "attachment_id": "image-ref",
    }))
    transport.add_text("It is a red square.")
    transports = TransportRegistry()
    transports.register("scripted", lambda: transport)
    runtime = AgentRuntime(transport_registry=transports, tool_registry=tools,
                           hooks=PipesHubAgentFactory._build_hooks(context))
    spec = AgentSpec(name="test", system_prompt="Answer the user.", tool_names=["analyze_image"],
                     model=ModelSpec(provider="scripted", model="text-only"), loop=ReActLoop())
    result = await Agent(spec, runtime).run(Goal(description="What is this image? ID image-ref"))
    assert result.success
    assert checker.await_count == 1
    assert model.ainvoke.await_args.args[0][0].content[1]["image_url"]["url"] == uri
    assert "A red square." in str(transport.calls[1]["messages"])
    assert uri not in str(transport.calls)
