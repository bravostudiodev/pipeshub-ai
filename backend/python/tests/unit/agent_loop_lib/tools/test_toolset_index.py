"""Named-source search must not let a shared provider word steal a match."""

from app.agent_loop_lib.tools.base import Tool, ToolOutput, ToolParameter
from app.agent_loop_lib.tools.registry import ToolRegistry
from app.agent_loop_lib.tools.toolset_index import ToolsetAwareToolIndex


class SearchTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> str:
        return f"/toolsets/{self._name}"

    @property
    def description(self) -> str:
        return "Search files and events"

    @property
    def short_description(self) -> str:
        return self.description

    @property
    def parameters(self) -> list[ToolParameter]:
        return []

    async def execute(self, **kwargs: object) -> ToolOutput:
        return ToolOutput(success=True, data=[])


def registry() -> ToolRegistry:
    tools = ToolRegistry()
    for name, app in (("calendar_search", "Google Calendar"), ("drive_search", "Google Drive")):
        tools.register_tool(SearchTool(name))
        tools.register_toolset(app, f"{app} — search", [name])
    return tools


async def test_full_google_drive_name_wins_over_calendar_at_limit_one() -> None:
    matches = await ToolsetAwareToolIndex().search(registry(), "search Google Drive files", limit=1)
    assert [match.summary.name for match in matches] == ["drive_search"]


async def test_full_google_calendar_name_wins_over_drive_at_limit_one() -> None:
    matches = await ToolsetAwareToolIndex().search(registry(), "search Google Calendar events", limit=1)
    assert [match.summary.name for match in matches] == ["calendar_search"]


async def test_both_named_apps_remain_discoverable_in_a_cross_source_query() -> None:
    matches = await ToolsetAwareToolIndex().search(registry(), "search Google Drive and Google Calendar", limit=2)
    assert {match.summary.name for match in matches} == {"drive_search", "calendar_search"}


async def test_partial_provider_name_retains_existing_fallback() -> None:
    matches = await ToolsetAwareToolIndex().search(registry(), "search Google", limit=2)
    assert {match.summary.name for match in matches} == {"drive_search", "calendar_search"}
