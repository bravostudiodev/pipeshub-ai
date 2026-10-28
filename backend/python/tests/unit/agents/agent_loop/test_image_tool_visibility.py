from types import SimpleNamespace

from app.agent_loop_lib.agent.spec import AgentSpec
from app.agent_loop_lib.agent.tool_loop import (
    initial_visible_tools,
    tool_schemas_for_turn,
)


class Registry:
    def __init__(self) -> None:
        self.names_list = [f"tool_{i:03}" for i in range(120)] + ["analyze_image"]

    def names(self) -> list[str]:
        return self.names_list

    def grouped_tool_names(self) -> set[str]:
        return set(self.names_list) - {"analyze_image"}

    def tools_in_toolset(self, name: str) -> list[str]:
        return []

    def has_toolsets(self) -> bool:
        return True

    def schemas(self, names: list[str]) -> list[str]:
        return names


def test_lazy_and_capped_grants_keep_image_tool() -> None:
    registry = Registry()
    runtime = SimpleNamespace(tool_registry=registry)
    lazy = AgentSpec(name="test", tool_names=registry.names_list, tool_disclosure="lazy")
    assert "analyze_image" in initial_visible_tools(lazy, runtime)
    eager = AgentSpec(name="test", tool_names=registry.names_list, tool_disclosure="eager")
    schemas = tool_schemas_for_turn(SimpleNamespace(visible_tools=None), eager, runtime)
    assert len(schemas) == 96
    assert "analyze_image" in schemas
