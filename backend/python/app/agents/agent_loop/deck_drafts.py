"""Slidev deck support for the coding-sandbox bridge.

A sandbox lives only for the message that created it, so a deck that failed
its checks (or that the user wants changed later) used to be lost with it and
the next message rebuilt it from nothing. The build helper
(`deployment/sandbox/slidev/build_deck.py`) therefore saves the project source
to `.oddjeeves/deck-draft.zip` on every build. This module stores that draft as
a hidden artifact of the conversation and unpacks it into `deck/` before the
first `run_code` of the next message.
"""

from __future__ import annotations

import io
import logging
import posixpath
import stat
import zipfile
from typing import TYPE_CHECKING, Protocol

from app.models.entities import ArtifactType, ArtifactVisibility
from app.services.artifact_registry import Actor

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext
    from app.services.artifact_registry.registry import ArtifactRegistryService


class _Downloads(Protocol):
    async def download_file(self, path: str) -> bytes: ...

logger = logging.getLogger(__name__)

# Must match `DRAFT_PATH` in build_deck.py.
DRAFT_SANDBOX_PATH = ".oddjeeves/deck-draft.zip"
DRAFT_ARTIFACT_NAME = "deck-draft.zip"
RESTORE_DIR = "deck"
MAX_DRAFT_ENTRIES = 500
MAX_DRAFT_BYTES = 25 * 1024 * 1024

RESTORED_NOTE = (
    "deck/ holds the presentation project saved from this conversation's last deck build "
    "({count} files). Continue from it: change only what is needed, then rerun the build "
    "helper on deck/. It keeps the same file name, so the user's existing presentation "
    "gets a new version."
)


def _normalized(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def find_draft_path(paths: list[str]) -> str | None:
    """The draft among a `run_code` call's reported output paths, if the build wrote one."""
    for path in paths:
        normalized = _normalized(path)
        if normalized == DRAFT_SANDBOX_PATH or normalized.endswith("/" + DRAFT_SANDBOX_PATH):
            return path
    return None


def is_deck_archive(file_name: str, content: bytes) -> bool:
    """A ZIP with a built `dist/index.html`: what the deck helper delivers."""
    if not file_name.lower().endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "dist/index.html" in archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def deck_project_dirs(paths: list[str]) -> set[str]:
    """Folders among `paths` that hold a Slidev project (they contain `slides.md`)."""
    return {
        posixpath.dirname(_normalized(path))
        for path in paths
        if posixpath.basename(_normalized(path)) == "slides.md"
    }


def in_deck_project(path: str, project_dirs: set[str]) -> bool:
    """Whether `path` is a source file of a deck project rather than a deliverable."""
    normalized = _normalized(path)
    return any(
        directory == "" or normalized.startswith(directory + "/") for directory in project_dirs
    )


def unpack_draft(content: bytes) -> dict[str, bytes]:
    """`{deck/<path>: bytes}` for the draft's files. Empty if the archive is unsafe or too big."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            if len(entries) > MAX_DRAFT_ENTRIES or sum(info.file_size for info in entries) > MAX_DRAFT_BYTES:
                logger.warning("deck draft skipped: %d entries exceed the restore limits", len(entries))
                return {}
            files: dict[str, bytes] = {}
            for info in entries:
                name = posixpath.normpath(info.filename.replace("\\", "/"))
                if name.startswith(("/", "../")) or name in (".", "..") or stat.S_ISLNK(info.external_attr >> 16):
                    logger.warning("deck draft skipped: unsafe entry %r", info.filename)
                    return {}
                files[f"{RESTORE_DIR}/{name}"] = archive.read(info)
            return files
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
        logger.warning("deck draft skipped: unreadable archive", exc_info=True)
        return {}


async def save_draft(
    context: AgentContext, registry: ArtifactRegistryService, backend: _Downloads, paths: list[str],
) -> None:
    """Store the draft a build just wrote as a hidden artifact (new version per build)."""
    path = find_draft_path(paths)
    if path is None:
        return
    try:
        content = await backend.download_file(path)
        await registry.register_output(
            actor=Actor(org_id=context.org_id, user_id=context.user_id),
            name=DRAFT_ARTIFACT_NAME,
            artifact_type=ArtifactType.CODE,
            mime_type="application/zip",
            content=content,
            conversation_id=context.conversation_id,
            source_tool="/toolsets/coding_sandbox/run_code",
            visibility=ArtifactVisibility.STAGING,
        )
    except Exception:
        logger.warning("could not save the deck draft for conversation %s", context.conversation_id, exc_info=True)


async def restore_draft_once(context: AgentContext, registry: ArtifactRegistryService | None) -> dict[str, bytes]:
    """Files to stage into `deck/` on the first `run_code` of this request, if a draft exists."""
    if context.deck_draft_restore_checked or registry is None or not context.conversation_id:
        return {}
    context.deck_draft_restore_checked = True
    actor = Actor(org_id=context.org_id, user_id=context.user_id)
    try:
        draft = await registry.resolve_by_logical_name(
            actor, DRAFT_ARTIFACT_NAME, conversation_id=context.conversation_id,
        )
        if draft is None:
            return {}
        content = await registry.get_content(actor=actor, artifact_id=draft.artifact_id)
    except Exception:
        logger.warning("could not load the deck draft for conversation %s", context.conversation_id, exc_info=True)
        return {}
    files = unpack_draft(content)
    if files:
        logger.info("restored deck draft v%s into %s/ (%d files)", draft.version, RESTORE_DIR, len(files))
    return files
