"""Offline, isolated Slidev rendering for generated web slide decks."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import posixpath
import re
import tarfile
import zipfile
from typing import Any

from app.agent_loop_lib.sandbox.coding.docker_client import (
    DockerClientProvider,
    get_default_provider,
)
from app.agent_loop_lib.sandbox.governor import get_default_governor
from app.agent_loop_lib.tools.base import ParameterType, Tool, ToolOutput, ToolParameter
from app.services.artifact_registry.models import Actor

logger = logging.getLogger(__name__)

SLIDEV_PATH_PATTERN = "/tools/slidev/**"
SLIDEV_MEMORY_LIMIT = "1g"
SLIDEV_NANO_CPUS = 1_000_000_000
SLIDEV_TIMEOUT_SECONDS = 120
SLIDEV_MAX_INPUT_BYTES = 32 * 1024 * 1024
SLIDEV_MAX_OUTPUT_BYTES = 100 * 1024 * 1024
SLIDEV_MAX_OUTPUT_FILES = 500
SLIDEV_MAX_FILE_BYTES = 20 * 1024 * 1024
SLIDEV_MAX_ZIP_BYTES = 25 * 1024 * 1024
_SUPPORTED_THEMES = frozenset({"default", "seriph"})
_SAFE_TEXT_EXTENSIONS = frozenset(
    {".md", ".txt", ".json", ".csv", ".vue", ".ts", ".js", ".css"}
)
_SAFE_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"})
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_RESERVED_PROJECT_PATHS = frozenset(
    {
        "slides.md",
        "package.json",
        "package-lock.json",
        "node_modules",
        "dist",
    }
)


class SlidevInputError(ValueError):
    """The requested deck or staged file is outside the supported contract."""


def _safe_relative_path(path: str) -> str:
    """Validate a model supplied project path without normalizing escapes."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise SlidevInputError(
            "Supporting file paths must be non-empty relative POSIX paths"
        )
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise SlidevInputError(
            f"Absolute supporting file path is not allowed: {path!r}"
        )
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SlidevInputError(f"Unsafe supporting file path: {path!r}")
    clean = posixpath.normpath(path)
    if (
        clean in _RESERVED_PROJECT_PATHS
        or clean.split("/", 1)[0] in _RESERVED_PROJECT_PATHS
    ):
        raise SlidevInputError(
            f"Supporting file cannot replace a renderer file: {path!r}"
        )
    extension = posixpath.splitext(clean)[1].lower()
    if extension not in _SAFE_TEXT_EXTENSIONS | _SAFE_IMAGE_EXTENSIONS:
        raise SlidevInputError(
            f"Unsupported supporting file type: {extension or '(none)'}"
        )
    return clean


def _normalize_slides(markdown: str) -> str:
    """Enforce the offline, supported Slidev configuration in headmatter."""
    if not isinstance(markdown, str) or not markdown.strip():
        raise SlidevInputError("Markdown must contain at least one slide")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - application dependency
        raise RuntimeError("Slidev configuration validation requires PyYAML") from exc

    match = _FRONTMATTER.match(markdown)
    if match:
        try:
            headmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise SlidevInputError(f"Invalid Slidev frontmatter: {exc}") from exc
        body = markdown[match.end() :]
    else:
        headmatter = {}
        body = markdown
    if not isinstance(headmatter, dict):
        raise SlidevInputError("Slidev frontmatter must be a YAML mapping")
    theme = headmatter.get("theme", "default")
    if theme not in _SUPPORTED_THEMES:
        raise SlidevInputError(
            "Only the preinstalled 'default' and 'seriph' themes are supported"
        )

    headmatter.update(
        {
            "theme": theme,
            "base": "./",
            "routerMode": "hash",
            "remoteAssets": False,
            "fonts": {"provider": "none"},
            "download": False,
            # Slidev's default favicon points at jsDelivr; an empty string
            # suppresses that default so exported decks stay fully offline.
            "favicon": "",
        }
    )
    rendered = yaml.safe_dump(headmatter, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{rendered}\n---\n\n{body.lstrip()}"


def _safe_archive_members(archive: bytes) -> dict[str, bytes]:
    """Read Docker's output tar without extracting paths onto the host."""
    if len(archive) > SLIDEV_MAX_OUTPUT_BYTES:
        raise SlidevInputError(
            "Slidev build output exceeds the 100 MiB extraction limit"
        )
    members: dict[str, bytes] = {}
    total_size = 0
    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    except tarfile.TarError as exc:
        raise SlidevInputError("Slidev returned an invalid output archive") from exc
    with tar:
        for member in tar:
            raw_name = member.name.removeprefix("./")
            if raw_name.startswith("dist/"):
                raw_name = raw_name[5:]
            path = _safe_output_path(raw_name)
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise SlidevInputError(
                    f"Unsupported entry in Slidev output: {member.name!r}"
                )
            if path in members:
                raise SlidevInputError(f"Duplicate output path: {path!r}")
            if member.size < 0 or member.size > SLIDEV_MAX_FILE_BYTES:
                raise SlidevInputError(f"Slidev output file is too large: {path!r}")
            if len(members) >= SLIDEV_MAX_OUTPUT_FILES:
                raise SlidevInputError("Slidev output contains too many files")
            total_size += member.size
            if total_size > SLIDEV_MAX_OUTPUT_BYTES:
                raise SlidevInputError(
                    "Slidev output exceeds the 100 MiB extraction limit"
                )
            stream = tar.extractfile(member)
            if stream is None:
                raise SlidevInputError(f"Could not read Slidev output file: {path!r}")
            content = stream.read(SLIDEV_MAX_FILE_BYTES + 1)
            if len(content) != member.size or len(content) > SLIDEV_MAX_FILE_BYTES:
                raise SlidevInputError(f"Slidev output changed while reading: {path!r}")
            members[path] = content
    if "index.html" not in members:
        raise SlidevInputError("Slidev build completed without an index.html")
    return members


def _safe_output_path(path: str) -> str:
    if not path or "\\" in path or "\x00" in path or path.startswith("/"):
        raise SlidevInputError(f"Unsafe Slidev output path: {path!r}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SlidevInputError(f"Unsafe Slidev output path: {path!r}")
    return path


def _make_project_zip(
    slides: str,
    project_files: dict[str, bytes],
    output_files: dict[str, bytes],
) -> bytes:
    readme = (
        "# Slidev presentation\n\n"
        "Open `dist/index.html` in a local HTTP server. For example, from this directory run:\n\n"
        "```sh\npython3 -m http.server 8000 --directory dist\n```\n\n"
        "Then open http://localhost:8000/. The built site uses hash routing and relative assets.\n"
        "`slides.md` and `public/` contain the editable source and included assets.\n"
        "This archive contains a static HTML/CSS/JavaScript site; it does not contain PPTX or PDF exports.\n"
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zipped:
        zipped.writestr("slides.md", slides)
        zipped.writestr("README.md", readme)
        for path, content in sorted(project_files.items()):
            zipped.writestr(path, content)
        for path, content in sorted(output_files.items()):
            zipped.writestr(f"dist/{path}", content)
    result = buffer.getvalue()
    if len(result) > SLIDEV_MAX_ZIP_BYTES:
        raise SlidevInputError(
            "Slidev ZIP exceeds the artifact registry's 25 MiB limit"
        )
    return result


def _tar_payload(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for path, content in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = 0o644
            info.uid = 1000
            info.gid = 1000
            tar.addfile(info, io.BytesIO(content))
    payload = output.getvalue()
    if len(payload) > SLIDEV_MAX_INPUT_BYTES:
        raise SlidevInputError("Slidev inputs exceed the 32 MiB staging limit")
    return payload


class DockerSlidevRenderer:
    """One fresh, offline container per render, using the shared Docker pool."""

    def __init__(
        self, image: str, *, provider: DockerClientProvider | None = None
    ) -> None:
        if not image or not image.strip():
            raise ValueError("SLIDEV_DOCKER_IMAGE must be configured")
        self.image = image
        self.provider = provider or get_default_provider()

    async def render(
        self, markdown: str, project_files: dict[str, bytes], *, org_id: str
    ) -> dict[str, bytes]:
        slides = _normalize_slides(markdown)
        staged = {"slides.md": slides.encode("utf-8"), **project_files}
        payload = _tar_payload(staged)
        governor = get_default_governor()
        lease = await governor.acquire(org_id=org_id)
        container = None
        try:
            try:
                present = await self.provider.ensure_image(self.image)
                if not present:
                    await self.provider.pull_image(self.image)
            except Exception as exc:
                raise RuntimeError(
                    f"Slidev renderer image is unavailable: {self.image}"
                ) from exc

            container = await _create_container_owned(
                self.provider,
                image=self.image,
                command=["sleep", "180"],
                working_dir="/workspace",
                user="1000:1000",
                network_mode="none",
                mem_limit=SLIDEV_MEMORY_LIMIT,
                nano_cpus=SLIDEV_NANO_CPUS,
                pids_limit=128,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                environment={"CI": "true", "HOME": "/home/node"},
                labels={"pipeshub.slidev": "render"},
            )
            await _owned_blocking(self.provider, container.start)
            accepted = await _owned_blocking(
                self.provider, container.put_archive, "/workspace", payload
            )
            if not accepted:
                raise RuntimeError("Docker rejected the staged Slidev project archive")
            execution = await _owned_blocking(
                self.provider,
                container.client.api.exec_create,
                container.id,
                ["npm", "run", "build"],
                workdir="/workspace",
                user="1000:1000",
            )
            await _owned_blocking(
                self.provider,
                container.client.api.exec_start,
                execution["Id"],
                detach=True,
            )
            async with asyncio.timeout(SLIDEV_TIMEOUT_SECONDS):
                while True:
                    state = await _owned_blocking(
                        self.provider,
                        container.client.api.exec_inspect,
                        execution["Id"],
                    )
                    if not state.get("Running"):
                        if state.get("ExitCode") != 0:
                            raise RuntimeError(
                                "Slidev build failed; check the deck theme and source files"
                            )
                        break
                    await asyncio.sleep(0.25)

            output_tar = await _owned_blocking(
                self.provider,
                _read_container_archive,
                container,
                "/workspace/dist",
            )
            return _safe_archive_members(output_tar)
        except TimeoutError as exc:
            raise RuntimeError(
                "Slidev build exceeded its 120 second execution limit"
            ) from exc
        finally:
            try:
                if container is not None:
                    await _cleanup_container(self.provider, container)
            finally:
                await lease.release()


async def _owned_blocking(
    provider: DockerClientProvider,
    fn: Any,  # noqa: ANN401 - Docker SDK operation
    *args: Any,  # noqa: ANN401 - Docker SDK positional arguments
    **kwargs: Any,  # noqa: ANN401 - Docker SDK keyword arguments
) -> Any:  # noqa: ANN401 - SDK result varies by operation
    """Do not let cancellation orphan an in-flight daemon operation."""
    task = asyncio.create_task(provider.run_blocking(fn, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            logger.debug(
                "Docker operation finished with an error during cancellation",
                exc_info=True,
            )
        raise


async def _create_container_owned(
    provider: DockerClientProvider,
    **kwargs: Any,  # noqa: ANN401 - Docker create options
) -> Any:  # noqa: ANN401 - Docker SDK container
    """Own a create result even when its caller is cancelled mid-request.

    Docker SDK calls run in worker threads and cannot be cancelled. Waiting
    for the call is not enough for `create`: its returned container must be
    removed before cancellation propagates and the governor lease is freed.
    """
    task = asyncio.create_task(
        provider.run_blocking(provider.client.containers.create, **kwargs)
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            container = await task
        except Exception:
            logger.debug(
                "Docker container creation failed during cancellation", exc_info=True
            )
        else:
            await _cleanup_container(provider, container)
        raise


def _read_container_archive(container: Any, path: str) -> bytes:  # noqa: ANN401 - Docker SDK object
    stream, _stat = container.get_archive(path)
    chunks: list[bytes] = []
    total = 0
    for chunk in stream:
        total += len(chunk)
        if total > SLIDEV_MAX_OUTPUT_BYTES:
            raise SlidevInputError(
                "Slidev output archive exceeds the 100 MiB transfer limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _cleanup_container(
    provider: DockerClientProvider,
    container: Any,  # noqa: ANN401 - Docker SDK object
) -> None:
    """Kill and remove before releasing the governor lease, including cancel paths."""
    task = asyncio.create_task(_cleanup_container_blocking(provider, container))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # The child task continues after caller cancellation; wait for daemon
        # cleanup before the governor slot is released.
        await task
        raise


async def _cleanup_container_blocking(
    provider: DockerClientProvider,
    container: Any,  # noqa: ANN401 - Docker SDK object
) -> None:
    try:
        await provider.run_blocking(container.kill)
    except Exception:
        logger.debug("Slidev container kill was unnecessary or failed", exc_info=True)
    try:
        await provider.run_blocking(container.remove, force=True, v=True)
    except Exception:
        logger.warning(
            "Failed to remove Slidev container %s",
            getattr(container, "id", "unknown"),
            exc_info=True,
        )


class RenderSlidevTool(Tool):
    """Render a markdown deck and return a single downloadable ZIP artifact."""

    def __init__(self, context: Any, renderer: DockerSlidevRenderer) -> None:  # noqa: ANN401 - request context
        self.context = context
        self.renderer = renderer

    @property
    def name(self) -> str:
        return "render_slidev"

    @property
    def short_description(self) -> str:
        return "Build an offline Slidev deck and return its website and editable source as one ZIP."

    @property
    def description(self) -> str:
        return (
            "Create a browser presentation from Markdown and return one ZIP containing the static "
            "HTML/CSS/JavaScript site, editable Markdown, supporting assets, and local serving README. "
            "Only the preinstalled default and seriph themes work. Include images as supporting_files; "
            "remote fonts, remote assets, external themes, npm dependencies, PDF/PPTX export, and hosted "
            "preview are not supported. Existing artifacts in this conversation can be supplied through "
            "input_artifacts; their access is checked for the current user before staging. These files "
            "are placed under public/input/<filename> and referenced without `public`, e.g. "
            "![Chart](/input/chart.svg)."
        )

    @property
    def path(self) -> str:
        return "/tools/slidev/render_slidev"

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="markdown",
                type=ParameterType.STRING,
                required=True,
                description="Complete Slidev Markdown source for the deck.",
            ),
            ToolParameter(
                name="supporting_files",
                type=ParameterType.ARRAY,
                required=False,
                default=None,
                items={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                description="Small text support files using safe relative paths, such as Vue components, CSS, or Markdown.",
            ),
            ToolParameter(
                name="input_artifacts",
                type=ParameterType.ARRAY,
                required=False,
                default=None,
                items={"type": "string"},
                description="Artifact names or IDs from this conversation. Each is resolved under the authenticated user's artifact permissions.",
            ),
        ]

    async def execute(
        self,
        markdown: str,
        supporting_files: list[dict[str, str]] | None = None,
        input_artifacts: list[str] | None = None,
        **kwargs: Any,  # noqa: ANN401 - tool adapter may pass extra schema values
    ) -> ToolOutput:
        try:
            project_files: dict[str, bytes] = {}
            for item in supporting_files or []:
                if not isinstance(item, dict) or not isinstance(
                    item.get("content"), str
                ):
                    raise SlidevInputError(
                        "Each supporting file needs a text path and content"
                    )
                path = _safe_relative_path(item.get("path"))
                project_files[path] = item["content"].encode("utf-8")

            registry = self.context.artifact_registry
            actor = Actor(org_id=self.context.org_id, user_id=self.context.user_id)
            for ref in input_artifacts or []:
                if not isinstance(ref, str) or not ref.strip():
                    continue
                if registry is None:
                    raise RuntimeError(
                        "Artifact storage is unavailable in this context"
                    )
                metadata = await registry.resolve(
                    actor=actor,
                    ref=ref,
                    conversation_id=self.context.conversation_id,
                )
                content = await registry.get_content(
                    actor=actor, artifact_id=metadata.artifact_id
                )
                basename = posixpath.basename(metadata.name)
                safe_name = _safe_relative_path(basename)
                if (
                    posixpath.splitext(safe_name)[1].lower()
                    not in _SAFE_IMAGE_EXTENSIONS | _SAFE_TEXT_EXTENSIONS
                ):
                    raise SlidevInputError(
                        f"Artifact type cannot be staged into Slidev: {basename!r}"
                    )
                project_files[f"public/input/{safe_name}"] = content

            total = sum(len(value) for value in project_files.values()) + len(
                markdown.encode("utf-8")
            )
            if total > SLIDEV_MAX_INPUT_BYTES:
                raise SlidevInputError("Slidev inputs exceed the 32 MiB staging limit")
            output = await self.renderer.render(
                markdown, project_files, org_id=self.context.org_id
            )
            zip_bytes = _make_project_zip(
                _normalize_slides(markdown), project_files, output
            )
            registry = self.context.artifact_registry
            if registry is None or not self.context.conversation_id:
                raise RuntimeError(
                    "Artifact storage is unavailable in this conversation"
                )
            from app.agents.agent_loop.sandbox_bridge import _register_and_deliver

            data: dict[str, Any] = {}
            registered = await _register_and_deliver(
                self.context,
                registry,
                [("slidev-presentation.zip", zip_bytes)],
                {"slidev-presentation.zip": "slidev-presentation.zip"},
                data,
                source_tool=self.path,
                code_artifact_id=None,
                code_artifact_version=None,
            )
            if not registered:
                errors = data.get("artifact_errors") or []
                message = (
                    errors[0].get("error")
                    if errors
                    else "Artifact storage rejected the generated ZIP"
                )
                raise RuntimeError(
                    f"The Slidev site built but its ZIP could not be saved: {message}"
                )
            data["_slidev_registered_artifacts"] = [
                metadata.model_dump() for metadata in registered
            ]
            return ToolOutput(
                success=True,
                data={
                    "success": True,
                    **data,
                    "message": "The presentation ZIP is attached to the response. It contains the static site, editable source, and local serving README.",
                },
            )
        except Exception as exc:
            logger.info("Slidev render failed: %s", exc, exc_info=True)
            return ToolOutput(success=False, error=str(exc))


def slidev_artifact_propagation(context: Any) -> Any:  # noqa: ANN401 - hook context protocol
    """Copy this tool's artifact registrations into its own run scope."""
    from app.agents.agent_loop.sandbox_bridge import _REGISTERED_ARTIFACTS_SLOT

    async def _middleware(ctx: Any, next_fn: Any) -> None:  # noqa: ANN401 - middleware protocol
        await next_fn()
        response = ctx.tool_response
        if ctx.tool_path != "/tools/slidev/render_slidev" or not response.success:
            return
        data = response.data if isinstance(response.data, dict) else {}
        newly_registered = data.pop("_slidev_registered_artifacts", [])
        if not newly_registered:
            return
        context.artifacts_produced_this_run = True
        if ctx.scope is not None:
            ctx.scope.turn.run.get(_REGISTERED_ARTIFACTS_SLOT).extend(newly_registered)

    return _middleware


def slidev_enabled() -> bool:
    return os.getenv("SLIDEV_ENABLED", "false").strip().lower() == "true"


def slidev_runtime_enabled(
    *, code_exec_enabled: bool, sandbox_mode: str | None = None
) -> bool:
    """Require the normal execution gate plus the explicit Slidev Docker gate."""
    mode = sandbox_mode if sandbox_mode is not None else os.getenv("SANDBOX_MODE", "")
    return code_exec_enabled and slidev_enabled() and mode.strip().lower() == "docker"


def build_slidev_renderer(*, image: str | None = None) -> DockerSlidevRenderer:
    configured_image = image or os.getenv("SLIDEV_DOCKER_IMAGE", "").strip()
    if not configured_image:
        raise RuntimeError("SLIDEV_DOCKER_IMAGE is required when SLIDEV_ENABLED=true")
    return DockerSlidevRenderer(configured_image)


def register_slidev_tool(
    tool_registry: Any,  # noqa: ANN401 - tool registry protocol
    context: Any,  # noqa: ANN401 - request context
    *,
    code_exec_enabled: bool,
) -> bool:
    """Register the optional tool only when both execution gates are open."""
    if not slidev_runtime_enabled(code_exec_enabled=code_exec_enabled):
        return False
    try:
        tool = RenderSlidevTool(context, build_slidev_renderer())
        tool_registry.register_tool(tool)
        tool_registry.register_toolset(
            "slidev",
            "Build offline browser presentations and download the static site as a ZIP.",
            [tool.name],
        )
        return True
    except Exception as exc:
        logger.warning("render_slidev is enabled but unavailable: %s", exc)
        return False
