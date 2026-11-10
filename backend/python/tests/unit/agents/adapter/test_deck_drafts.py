"""Deck drafts: a deck project survives the per-message sandbox, and a failed
deck run never spills its source files into the chat as loose artifacts."""

from __future__ import annotations

import io
import stat
import zipfile
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agent_loop_lib.core.scope import RunScope, ToolScope, TurnScope
from app.agent_loop_lib.core.types import AgentResult, Goal
from app.agent_loop_lib.hooks.middleware.context import (
    AgentLifecycleContext,
    ToolCallContext,
    ToolResultContext,
)
from app.agent_loop_lib.sandbox.manager import SandboxManager, SandboxType
from app.agent_loop_lib.tools.base import ToolOutput
from app.agent_loop_lib.tools.builtin.sandbox import input_staging
from app.agent_loop_lib.tools.builtin.sandbox.input_staging import (
    peek_staged_input_files,
)
from app.agents.agent_loop import deck_drafts
from app.agents.agent_loop.context import AgentContext
from app.agents.agent_loop.sandbox_bridge import (
    coding_sandbox_artifact_bridge,
    coding_sandbox_artifact_staging,
    coding_sandbox_result_propagation,
)
from app.models.entities import ArtifactType, ArtifactVisibility, LifecycleStatus
from app.services.artifact_registry import ArtifactMetadata

if TYPE_CHECKING:
    from collections.abc import Iterator

RUN_CODE = "/toolsets/coding_sandbox/run_code"


def _zip(entries: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return buf.getvalue()


def _metadata(**overrides: object) -> ArtifactMetadata:
    defaults: dict[str, object] = {
        "artifact_id": "rec-1", "org_id": "org-1", "conversation_id": "conv-1", "name": "Q4 Review.zip",
        "logical_name": "Q4 Review.zip", "artifact_type": ArtifactType.PRESENTATION,
        "mime_type": "application/zip", "lifecycle_status": LifecycleStatus.PUBLISHED,
        "version": 1, "size_bytes": 9, "document_id": "doc-1",
    }
    defaults.update(overrides)
    return ArtifactMetadata(**defaults)


def _context() -> AgentContext:
    return AgentContext(
        org_id="org-1", user_id="user-1", user_email="u@example.com", logger=MagicMock(),
        retrieval_service=MagicMock(config_service=MagicMock()), conversation_id="conv-1",
    )


class _Backend:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files
        self.sandbox_id = f"fake-{uuid4().hex[:8]}"

    async def provision(self) -> None:
        return None

    async def destroy(self) -> None:
        return None

    async def download_file(self, path: str) -> bytes:
        return self._files[path]


def _tool_scope() -> tuple[ToolScope, RunScope]:
    run_scope = RunScope(identity=MagicMock(), spec=MagicMock(), runtime=MagicMock(), goal=MagicMock())
    tool_scope = ToolScope(turn=TurnScope(run=run_scope, turn_index=0), call=MagicMock(), tool_path=RUN_CODE)
    return tool_scope, run_scope


async def _next() -> None:
    return None


class TestUnpackDraft:
    def test_files_land_under_deck(self) -> None:
        files = deck_drafts.unpack_draft(_zip({"slides.md": b"# Hi", "public/logo.svg": b"<svg/>"}))
        assert files == {"deck/slides.md": b"# Hi", "deck/public/logo.svg": b"<svg/>"}

    @pytest.mark.parametrize("name", ["../escape.txt", "/etc/passwd"])
    def test_path_escape_rejects_the_whole_draft(self, name: str) -> None:
        assert deck_drafts.unpack_draft(_zip({"slides.md": b"# Hi", name: b"x"})) == {}

    def test_symlink_rejects_the_whole_draft(self) -> None:
        assert deck_drafts.unpack_draft(_zip({"slides.md": b"# Hi"}, symlink="public/link")) == {}

    def test_too_many_entries_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(deck_drafts, "MAX_DRAFT_ENTRIES", 1)
        assert deck_drafts.unpack_draft(_zip({"a": b"1", "b": b"2"})) == {}

    def test_garbage_is_skipped(self) -> None:
        assert deck_drafts.unpack_draft(b"not a zip") == {}


def test_deck_archive_needs_a_built_index() -> None:
    assert deck_drafts.is_deck_archive("Q4.zip", _zip({"dist/index.html": b"<html/>", "slides.md": b""}))
    assert not deck_drafts.is_deck_archive("data.zip", _zip({"rows.csv": b"a,b"}))
    assert not deck_drafts.is_deck_archive("Q4.html", b"<html/>")


def test_deck_project_files_are_recognised_by_their_slides_md() -> None:
    paths = ["deck/slides.md", "deck/public/fonts/Inter.otf", "deck2/slides.md", "chart.png"]
    dirs = deck_drafts.deck_project_dirs(paths)
    assert dirs == {"deck", "deck2"}
    assert deck_drafts.in_deck_project("deck/public/fonts/Inter.otf", dirs)
    assert not deck_drafts.in_deck_project("chart.png", dirs)
    assert not deck_drafts.in_deck_project("deck-notes.txt", dirs)


class TestRestoreIntoSandbox:
    @pytest.fixture(autouse=True)
    def _reset_staged(self) -> Iterator[None]:
        token = input_staging._staged_input_files.set(None)
        yield
        input_staging._staged_input_files.reset(token)

    def _registry(self, draft: bytes | None) -> MagicMock:
        registry = MagicMock()
        registry.resolve_by_logical_name = AsyncMock(
            return_value=_metadata(artifact_id="draft-1", name="deck-draft.zip", version=3) if draft else None,
        )
        registry.get_content = AsyncMock(return_value=draft)
        registry.register_output = AsyncMock(return_value=(_metadata(), 1))
        return registry

    async def test_first_run_code_of_a_message_restores_the_draft_once(self, monkeypatch) -> None:
        context = _context()
        registry = self._registry(_zip({"slides.md": b"# Saved"}))
        monkeypatch.setattr(AgentContext, "artifact_registry", property(lambda self: registry))
        staging = coding_sandbox_artifact_staging(context)

        first = ToolCallContext(tool_path=RUN_CODE, tool_input={"code": "print(1)"})
        await staging(first, _next)
        assert peek_staged_input_files() == {"deck/slides.md": b"# Saved"}
        assert first.metadata["deck_project_restored"] == 1

        # Each real tool call runs in its own task with a clean staging var.
        input_staging._staged_input_files.set(None)
        second = ToolCallContext(tool_path=RUN_CODE, tool_input={"code": "print(2)"})
        await staging(second, _next)
        assert peek_staged_input_files() is None
        assert registry.resolve_by_logical_name.await_count == 1

    async def test_other_sandbox_tools_do_not_spend_the_restore(self, monkeypatch) -> None:
        context = _context()
        registry = self._registry(_zip({"slides.md": b"# Saved"}))
        monkeypatch.setattr(AgentContext, "artifact_registry", property(lambda self: registry))
        staging = coding_sandbox_artifact_staging(context)

        await staging(ToolCallContext(tool_path="/toolsets/coding_sandbox/install_packages", tool_input={}), _next)
        assert context.deck_draft_restore_checked is False

        await staging(ToolCallContext(tool_path=RUN_CODE, tool_input={"code": "x"}), _next)
        assert peek_staged_input_files() == {"deck/slides.md": b"# Saved"}

    async def test_conversation_without_a_draft_stages_nothing(self, monkeypatch) -> None:
        context = _context()
        registry = self._registry(None)
        monkeypatch.setattr(AgentContext, "artifact_registry", property(lambda self: registry))

        ctx = ToolCallContext(tool_path=RUN_CODE, tool_input={"code": "x"})
        await coding_sandbox_artifact_staging(context)(ctx, _next)

        assert peek_staged_input_files() is None
        assert "deck_project_restored" not in ctx.metadata

    async def test_model_is_told_the_project_was_restored(self, monkeypatch) -> None:
        context = _context()
        monkeypatch.setattr(AgentContext, "artifact_registry", property(lambda self: MagicMock()))
        ctx = ToolResultContext(
            tool_path=RUN_CODE, tool_use_id=uuid4(),
            tool_response=ToolOutput(success=True, data={"artifacts": [], "sandbox_id": None}),
            metadata={"deck_project_restored": 12},
        )
        await coding_sandbox_artifact_bridge(context, SandboxManager())(ctx, _next)
        assert "deck/ holds the presentation project" in ctx.tool_response.data["deck_project_restored"]
        assert "12 files" in ctx.tool_response.data["deck_project_restored"]


class TestBuildOutputs:
    async def _run_bridge(
        self, files: dict[str, bytes], paths: list[str], registry: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[AgentContext, SandboxManager, RunScope, ToolResultContext]:
        context = _context()
        monkeypatch.setattr(AgentContext, "artifact_registry", property(lambda self: registry))
        manager = SandboxManager()
        manager.register_backend_factory(SandboxType.CODING, lambda: _Backend(files))
        sandbox_id, _ = await manager.get_or_create(SandboxType.CODING)
        tool_scope, run_scope = _tool_scope()
        ctx = ToolResultContext(
            tool_path=RUN_CODE, tool_use_id=uuid4(),
            tool_response=ToolOutput(success=True, data={"artifacts": paths, "sandbox_id": sandbox_id}),
            scope=tool_scope,
        )
        with patch("app.agents.agent_loop.sandbox_bridge.register_task"):
            await coding_sandbox_artifact_bridge(context, manager)(ctx, _next)
        return context, manager, run_scope, ctx

    async def test_build_draft_is_saved_hidden_and_never_shown(self, monkeypatch) -> None:
        draft = _zip({"slides.md": b"# Q4"})
        registry = MagicMock()
        registry.register_output = AsyncMock(return_value=(_metadata(name="deck-draft.zip"), 1))
        registry.get_download_url = AsyncMock(return_value="")
        _, _, _, ctx = await self._run_bridge(
            {".oddjeeves/deck-draft.zip": draft}, [".oddjeeves/deck-draft.zip", "deck/slides.md"],
            registry, monkeypatch,
        )

        registry.register_output.assert_awaited_once()
        kwargs = registry.register_output.await_args.kwargs
        assert kwargs["name"] == "deck-draft.zip"
        assert kwargs["visibility"] == ArtifactVisibility.STAGING
        assert kwargs["content"] == draft
        assert ctx.tool_response.data["artifacts"] == []

    async def test_delivered_deck_is_registered_as_a_presentation(self, monkeypatch) -> None:
        deck = _zip({"dist/index.html": b"<html/>", "slides.md": b"# Q4"})
        registry = MagicMock()
        registry.register_output = AsyncMock(return_value=(_metadata(), 1))
        registry.get_download_url = AsyncMock(return_value="https://blob.example/q4")
        await self._run_bridge({"output/Q4 Review.zip": deck}, ["output/Q4 Review.zip"], registry, monkeypatch)

        assert registry.register_output.await_args.kwargs["artifact_type"] == ArtifactType.PRESENTATION

    async def test_failed_deck_run_does_not_spill_project_files_as_cards(self, monkeypatch) -> None:
        files = {
            "deck/slides.md": b"# Q4", "deck/public/fonts/Inter.otf": b"font",
            "deck2/slides.md": b"# Q4 again", "notes.txt": b"real scratch",
        }
        registry = MagicMock()
        registry.register_output = AsyncMock(return_value=(_metadata(name="notes.txt"), 1))
        registry.get_download_url = AsyncMock(return_value="")
        context, manager, run_scope, _ = await self._run_bridge(files, list(files), registry, monkeypatch)

        result = AgentResult(goal=Goal(description="test"))
        with patch("app.agents.agent_loop.sandbox_bridge.register_task"):
            await coding_sandbox_result_propagation(context, manager)(
                AgentLifecycleContext(result=result, scope=run_scope), _next,
            )

        rescued = [call.kwargs["name"] for call in registry.register_output.await_args_list]
        assert rescued == ["notes.txt"]
