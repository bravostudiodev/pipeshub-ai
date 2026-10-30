import asyncio
import io
import sys
import tarfile
import threading
import zipfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agent_loop_lib.tools.registry import ToolRegistry
from app.agents.agent_loop import slidev


def test_normalize_slides_enforces_offline_configuration() -> None:
    normalized = slidev._normalize_slides("# Welcome\n\n---\n# One")
    assert "theme: default" in normalized
    assert "base: ./" in normalized
    assert "routerMode: hash" in normalized
    assert "remoteAssets: false" in normalized
    assert "favicon: ''" in normalized
    assert "provider: none" in normalized
    assert "download: false" in normalized


def test_normalize_slides_rejects_non_preinstalled_theme() -> None:
    with pytest.raises(slidev.SlidevInputError, match="preinstalled"):
        slidev._normalize_slides("---\ntheme: github\n---\n# slide")


def test_registration_requires_code_gate_slidev_gate_and_docker_mode(
    monkeypatch,
) -> None:
    registry = ToolRegistry()
    context = SimpleNamespace()
    monkeypatch.setenv("SLIDEV_ENABLED", "true")
    monkeypatch.setenv("SLIDEV_DOCKER_IMAGE", "registry/slidev:1")
    monkeypatch.setenv("SANDBOX_MODE", "docker")
    monkeypatch.setattr(slidev, "build_slidev_renderer", lambda: object())

    assert not slidev.register_slidev_tool(registry, context, code_exec_enabled=False)
    assert not registry.has("render_slidev")
    assert slidev.register_slidev_tool(registry, context, code_exec_enabled=True)
    assert registry.has("render_slidev")
    assert registry.tools_in_toolset("slidev") == ["render_slidev"]


@pytest.mark.parametrize(
    "path", ["../escape.png", "/tmp/a.png", "a\\b.png", "package.json", "x.bin"]
)
def test_supporting_paths_reject_escape_and_reserved_files(path: str) -> None:
    with pytest.raises(slidev.SlidevInputError):
        slidev._safe_relative_path(path)


def test_output_archive_rejects_symlink_and_traversal() -> None:
    for name, kind in (("index.html", "symlink"), ("../escape", "file")):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            item = tarfile.TarInfo(name)
            if kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "../../etc/passwd"
                archive.addfile(item)
            else:
                item.size = 1
                archive.addfile(item, io.BytesIO(b"x"))
        with pytest.raises(slidev.SlidevInputError):
            slidev._safe_archive_members(output.getvalue())


def test_output_archive_rejects_duplicate_and_hardlink_members() -> None:
    duplicate = io.BytesIO()
    with tarfile.open(fileobj=duplicate, mode="w") as archive:
        for _ in range(2):
            item = tarfile.TarInfo("index.html")
            item.size = 1
            archive.addfile(item, io.BytesIO(b"x"))
    with pytest.raises(slidev.SlidevInputError, match="Duplicate"):
        slidev._safe_archive_members(duplicate.getvalue())

    hardlink = io.BytesIO()
    with tarfile.open(fileobj=hardlink, mode="w") as archive:
        item = tarfile.TarInfo("index.html")
        item.type = tarfile.LNKTYPE
        item.linkname = "other"
        archive.addfile(item)
    with pytest.raises(slidev.SlidevInputError, match="Unsupported entry"):
        slidev._safe_archive_members(hardlink.getvalue())


def test_output_archive_enforces_file_count_and_per_file_limits(monkeypatch) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in (("index.html", b"html"), ("app.js", b"js")):
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))

    monkeypatch.setattr(slidev, "SLIDEV_MAX_OUTPUT_FILES", 1)
    with pytest.raises(slidev.SlidevInputError, match="too many files"):
        slidev._safe_archive_members(output.getvalue())
    monkeypatch.setattr(slidev, "SLIDEV_MAX_OUTPUT_FILES", 500)
    monkeypatch.setattr(slidev, "SLIDEV_MAX_FILE_BYTES", 3)
    with pytest.raises(slidev.SlidevInputError, match="too large"):
        slidev._safe_archive_members(output.getvalue())


def test_project_zip_contains_static_site_editable_source_and_local_readme() -> None:
    zipped = slidev._make_project_zip(
        "# editable slides",
        {"public/hero.svg": b"<svg/>"},
        {"index.html": b"<html/>", "assets/app.js": b"app"},
    )
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        names = set(archive.namelist())
        assert {
            "slides.md",
            "README.md",
            "public/hero.svg",
            "dist/index.html",
            "dist/assets/app.js",
        } <= names
        assert b"python3 -m http.server" in archive.read("README.md")


class _FakeLease:
    def __init__(self) -> None:
        self.releases = 0

    async def release(self) -> None:
        self.releases += 1


class _FakeGovernor:
    def __init__(self, lease: _FakeLease) -> None:
        self.lease = lease

    async def acquire(self, *, org_id: str) -> _FakeLease:
        return self.lease


@pytest.mark.asyncio
async def test_cancel_during_container_create_removes_result_before_releasing_lease(
    monkeypatch,
) -> None:
    entered = threading.Event()
    finish_create = threading.Event()
    lease = _FakeLease()
    container = SimpleNamespace(
        id="created-after-cancel",
        kill=lambda: setattr(container, "killed", getattr(container, "killed", 0) + 1),
        remove=lambda **_kwargs: setattr(
            container, "removed", getattr(container, "removed", 0) + 1
        ),
    )

    def create(**_kwargs: object) -> SimpleNamespace:
        entered.set()
        finish_create.wait(timeout=3)
        return container

    async def run_blocking(fn, *args, **kwargs) -> object:
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: fn(*args, **kwargs),
        )

    provider = SimpleNamespace(
        client=SimpleNamespace(containers=SimpleNamespace(create=create)),
        ensure_image=AsyncMock(return_value=True),
        pull_image=AsyncMock(),
        run_blocking=run_blocking,
    )
    monkeypatch.setattr(slidev, "get_default_governor", lambda: _FakeGovernor(lease))
    renderer = slidev.DockerSlidevRenderer("test/slidev:local", provider=provider)
    task = asyncio.create_task(renderer.render("# One", {}, org_id="org"))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert lease.releases == 0
    finish_create.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert container.killed == 1
    assert container.removed == 1
    assert lease.releases == 1


def _make_output_tar() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in (
            ("index.html", b"<html></html>"),
            ("assets/app.js", b"app"),
        ):
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


def _docker_test_provider(
    *, running: bool = False, exit_code: int = 0
) -> tuple[object, dict[str, object], SimpleNamespace]:
    captured: dict[str, object] = {}
    container = SimpleNamespace(id="slidev-test", killed=0, removed=0)

    def create(**kwargs: object) -> SimpleNamespace:
        captured["create"] = kwargs
        return container

    def put_archive(path: str, payload: bytes) -> bool:
        captured["stage_path"] = path
        captured["stage_payload"] = payload
        return True

    def exec_create(
        _container_id: str, command: list[str], **kwargs: object
    ) -> dict[str, str]:
        captured["command"] = command
        captured["exec_options"] = kwargs
        return {"Id": "exec-1"}

    def exec_start(_exec_id: str, **kwargs: object) -> None:
        captured["exec_start"] = kwargs

    def exec_inspect(_exec_id: str) -> dict[str, object]:
        return {"Running": running, "ExitCode": exit_code}

    def get_archive(path: str) -> tuple[list[bytes], dict[str, object]]:
        captured["output_path"] = path
        return [_make_output_tar()], {}

    def kill() -> None:
        container.killed += 1

    def remove(**_kwargs: object) -> None:
        container.removed += 1

    container.start = lambda: None
    container.put_archive = put_archive
    container.client = SimpleNamespace(
        api=SimpleNamespace(
            exec_create=exec_create,
            exec_start=exec_start,
            exec_inspect=exec_inspect,
        )
    )
    container.get_archive = get_archive
    container.kill = kill
    container.remove = remove

    async def run_blocking(
        fn: Any,  # noqa: ANN401
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401 - fake SDK runner
        return fn(*args, **kwargs)

    provider = SimpleNamespace(
        client=SimpleNamespace(containers=SimpleNamespace(create=create)),
        ensure_image=AsyncMock(return_value=True),
        pull_image=AsyncMock(),
        run_blocking=run_blocking,
    )
    return provider, captured, container


@pytest.mark.asyncio
async def test_success_render_uses_bounded_offline_container_and_releases_lease(
    monkeypatch,
) -> None:
    provider, captured, container = _docker_test_provider()
    lease = _FakeLease()
    monkeypatch.setattr(slidev, "get_default_governor", lambda: _FakeGovernor(lease))
    renderer = slidev.DockerSlidevRenderer("registry/slidev:1", provider=provider)

    output = await renderer.render("# Hello", {"public/a.svg": b"<svg/>"}, org_id="org")

    create = captured["create"]
    assert create["network_mode"] == "none"
    assert create["user"] == "1000:1000"
    assert create["mem_limit"] == "1g"
    assert create["nano_cpus"] == 1_000_000_000
    assert create["cap_drop"] == ["ALL"]
    assert create["security_opt"] == ["no-new-privileges:true"]
    assert captured["command"] == ["npm", "run", "build"]
    assert captured["exec_options"]["user"] == "1000:1000"
    assert captured["stage_path"] == "/workspace"
    with tarfile.open(
        fileobj=io.BytesIO(captured["stage_payload"]), mode="r:"
    ) as archive:
        staged = archive.getmember("public/a.svg")
        assert (staged.uid, staged.gid, staged.mode) == (1000, 1000, 0o644)
    assert output == {"index.html": b"<html></html>", "assets/app.js": b"app"}
    assert container.killed == 1
    assert container.removed == 1
    assert lease.releases == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("running", "exit_code", "expected"),
    [(False, 2, "failed"), (True, 0, "120 second")],
)
async def test_failed_or_timed_out_build_is_cleaned_up(
    monkeypatch, running, exit_code, expected
) -> None:
    provider, _captured, container = _docker_test_provider(
        running=running, exit_code=exit_code
    )
    lease = _FakeLease()
    monkeypatch.setattr(slidev, "get_default_governor", lambda: _FakeGovernor(lease))
    monkeypatch.setattr(slidev, "SLIDEV_TIMEOUT_SECONDS", 0.01)
    renderer = slidev.DockerSlidevRenderer("registry/slidev:1", provider=provider)

    with pytest.raises(RuntimeError, match=expected):
        await renderer.render("# Hello", {}, org_id="org")
    assert container.killed == 1
    assert container.removed == 1
    assert lease.releases == 1


@pytest.mark.asyncio
async def test_input_artifacts_are_resolved_through_actor_and_conversation_acl() -> (
    None
):
    denied_registry = SimpleNamespace(
        resolve=AsyncMock(side_effect=PermissionError("denied"))
    )
    renderer = SimpleNamespace(render=AsyncMock())
    context = SimpleNamespace(
        artifact_registry=denied_registry,
        org_id="org-1",
        user_id="user-9",
        conversation_id="conversation-2",
    )
    tool = slidev.RenderSlidevTool(context, renderer)

    result = await tool.execute(markdown="# One", input_artifacts=["private.svg"])

    assert result.success is False
    args, kwargs = denied_registry.resolve.await_args
    assert args == ()
    assert kwargs["actor"].org_id == "org-1"
    assert kwargs["actor"].user_id == "user-9"
    assert kwargs["conversation_id"] == "conversation-2"
    renderer.render.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_output_registration_is_not_reported_as_success(
    monkeypatch,
) -> None:
    registry = SimpleNamespace(
        resolve=AsyncMock(
            return_value=SimpleNamespace(name="reference.svg", artifact_id="artifact-1")
        ),
        get_content=AsyncMock(return_value=b"<svg/>"),
    )
    renderer = SimpleNamespace(
        render=AsyncMock(return_value={"index.html": b"<html/>"})
    )
    context = SimpleNamespace(
        artifact_registry=registry,
        org_id="org-1",
        user_id="user-9",
        conversation_id="conversation-2",
    )

    async def reject_registration(
        _context: object,
        _registry: object,
        _fetched: list[tuple[str, bytes]],
        _names: dict[str, str],
        data: dict[str, Any],
        **_kwargs: Any,  # noqa: ANN401
    ) -> list[Any]:
        data["artifact_errors"] = [{"error": "store unavailable"}]
        return []

    monkeypatch.setitem(
        sys.modules,
        "app.agents.agent_loop.sandbox_bridge",
        SimpleNamespace(_register_and_deliver=reject_registration),
    )
    tool = slidev.RenderSlidevTool(context, renderer)
    result = await tool.execute(markdown="# One", input_artifacts=["artifact-1"])

    assert result.success is False
    assert "could not be saved" in result.error
    registry.resolve.assert_awaited_once()
    registry.get_content.assert_awaited_once()
    renderer.render.assert_awaited_once()
    assert renderer.render.await_args.args[1] == {
        "public/input/reference.svg": b"<svg/>"
    }


@pytest.mark.asyncio
async def test_artifact_metadata_propagates_to_each_run_scope(monkeypatch) -> None:
    slot = object()
    monkeypatch.setitem(
        sys.modules,
        "app.agents.agent_loop.sandbox_bridge",
        SimpleNamespace(_REGISTERED_ARTIFACTS_SLOT=slot),
    )
    context = SimpleNamespace(artifacts_produced_this_run=False)
    middleware = slidev.slidev_artifact_propagation(context)
    scope_lists = [[], []]

    async def next_fn() -> None:
        return None

    for index, target in enumerate(scope_lists):
        data = {"_slidev_registered_artifacts": [{"id": f"artifact-{index}"}]}
        run = SimpleNamespace(
            get=lambda requested, target=target: target if requested is slot else None
        )
        scope = SimpleNamespace(turn=SimpleNamespace(run=run))
        response = SimpleNamespace(success=True, data=data)
        ctx = SimpleNamespace(
            tool_response=response,
            tool_path="/tools/slidev/render_slidev",
            scope=scope,
        )
        await middleware(ctx, next_fn)
        assert "_slidev_registered_artifacts" not in data

    assert scope_lists == [[{"id": "artifact-0"}], [{"id": "artifact-1"}]]
    assert context.artifacts_produced_this_run is True
