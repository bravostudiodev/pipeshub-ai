"""Bounded, in-memory access to built files in a Slidev presentation archive.

Callers must authorize the exact artifact version before using this module.
The archive is never extracted to disk. The index gets a tiny storage shim so
Slidev can run inside an opaque-origin ``sandbox=allow-scripts`` iframe.
"""

from __future__ import annotations

import io
import lzma
import mimetypes
import posixpath
import stat
import threading
import zipfile
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_MEMBERS = 500
MAX_CACHE_BYTES = 128 * 1024 * 1024

# Prefer explicit browser MIME types; do not trust ZIP metadata.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".pdf": "application/pdf",
}

_STORAGE_SHIM = b"""<script>(function(){for(const key of ['localStorage','sessionStorage']){const values=new Map();const store={getItem:k=>values.has(String(k))?values.get(String(k)):null,setItem:(k,v)=>values.set(String(k),String(v)),removeItem:k=>values.delete(String(k)),clear:()=>values.clear(),key:i=>Array.from(values.keys())[i]??null,get length(){return values.size}};Object.defineProperty(window,key,{value:store,configurable:true});}})();</script>"""


class InvalidDeckArchive(ValueError):
    """An archive cannot safely be used as a deck preview."""


@dataclass(frozen=True)
class DeckFile:
    content: bytes
    content_type: str


class DeckArchiveCache:
    """Small LRU of immutable files; authorization is never cached here."""

    def __init__(self, max_bytes: int = MAX_CACHE_BYTES) -> None:
        self._max_bytes = max_bytes
        self._size = 0
        self._entries: OrderedDict[
            tuple[str, str, str, int, str], dict[str, DeckFile]
        ] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: tuple[str, str, str, int, str], path: str) -> DeckFile | None:
        normalized = _validate_path(path)
        with self._lock:
            files = self._entries.get(key)
            if files is None:
                return None
            self._entries.move_to_end(key)
            try:
                return files[normalized]
            except KeyError:
                raise InvalidDeckArchive("Deck file unavailable") from None

    def put(
        self, key: tuple[str, str, str, int, str], files: dict[str, DeckFile]
    ) -> None:
        size = sum(len(item.content) for item in files.values())
        if size > self._max_bytes:
            return
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._size -= sum(len(item.content) for item in previous.values())
            while self._entries and self._size + size > self._max_bytes:
                _, oldest = self._entries.popitem(last=False)
                self._size -= sum(len(item.content) for item in oldest.values())
            self._entries[key] = files
            self._size += size


# Only file bytes are cached. Callers must reauthorize actor/share and resolve
# the version hash before lookup; the key isolates org, user, artifact, version.
deck_archive_cache = DeckArchiveCache()


def _content_type(path: str) -> str:
    extension = posixpath.splitext(path)[1].lower()
    return (
        CONTENT_TYPES.get(extension)
        or mimetypes.guess_type(path)[0]
        or "application/octet-stream"
    )


def _validate_path(name: str) -> str:
    if (
        not name
        or "\\" in name
        or any(ord(char) < 32 for char in name)
        or name.startswith("/")
    ):
        raise InvalidDeckArchive("Unsafe archive path")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts) or ":" in parts[0]:
        raise InvalidDeckArchive("Unsafe archive path")
    return name


def _validate_archive(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Validate every central-directory entry, but do not decompress assets."""
    entries = archive.infolist()
    if len(entries) > MAX_MEMBERS:
        raise InvalidDeckArchive("Archive contains too many entries")
    seen: set[str] = set()
    files: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for entry in entries:
        directory = entry.is_dir()
        name = _validate_path(
            entry.filename.rstrip("/") if directory else entry.filename
        )
        if name in seen:
            raise InvalidDeckArchive("Duplicate archive path")
        seen.add(name)
        mode = (entry.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode)
        if (
            kind not in (0, stat.S_IFREG, stat.S_IFDIR)
            or (kind == stat.S_IFDIR) != directory
            and kind != 0
        ):
            raise InvalidDeckArchive("Unsupported archive entry")
        if entry.flag_bits & 1:
            raise InvalidDeckArchive("Encrypted archive entries are not supported")
        if entry.file_size > MAX_MEMBER_BYTES:
            raise InvalidDeckArchive("Archive entry exceeds the size limit")
        total += entry.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise InvalidDeckArchive("Archive exceeds the expanded size limit")
        if directory or not name.startswith("dist/"):
            continue
        relative = _validate_path(name[len("dist/") :])
        files[relative] = entry
    if "index.html" not in files:
        raise InvalidDeckArchive("Deck is missing dist/index.html")
    return files


def _read_entry(
    archive: zipfile.ZipFile, entry: zipfile.ZipInfo, path: str
) -> DeckFile:
    with archive.open(entry) as stream:
        content = stream.read(MAX_MEMBER_BYTES + 1)
    if len(content) != entry.file_size or len(content) > MAX_MEMBER_BYTES:
        raise InvalidDeckArchive("Invalid archive entry size")
    if path == "index.html":
        content = _inject_storage_shim(content)
    return DeckFile(content=content, content_type=_content_type(path))


def read_deck_archive(data: bytes) -> dict[str, DeckFile]:
    """Validate and read all bounded files under ``dist/`` for tests/tools."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise InvalidDeckArchive("Archive exceeds the size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = _validate_archive(archive)
            return {
                path: _read_entry(archive, entry, path)
                for path, entry in entries.items()
            }
    except InvalidDeckArchive:
        raise
    except (
        zipfile.BadZipFile,
        EOFError,
        OSError,
        RuntimeError,
        NotImplementedError,
        lzma.LZMAError,
        zlib.error,
    ) as exc:
        raise InvalidDeckArchive("Invalid deck archive") from exc


async def get_cached_deck_file_async(
    cache: DeckArchiveCache,
    key: tuple[str, str, str, int, str],
    path: str,
    load_archive: Callable[[], Awaitable[dict[str, DeckFile]]],
) -> DeckFile:
    """Async counterpart for loaders that fetch authorized bytes from storage."""
    normalized = _validate_path(path)
    cached = cache.get(key, normalized)
    if cached is not None:
        return cached
    files = await load_archive()
    cache.put(key, files)
    try:
        return files[normalized]
    except KeyError:
        raise InvalidDeckArchive("Deck file unavailable") from None


def _inject_storage_shim(html: bytes) -> bytes:
    """Provide per-frame in-memory storage without granting same-origin access."""
    head = html.lower().find(b"<head")
    if head >= 0:
        end = html.find(b">", head)
        if end >= 0:
            return html[: end + 1] + _STORAGE_SHIM + html[end + 1 :]
    return _STORAGE_SHIM + html


def get_deck_file(data: bytes, path: str) -> DeckFile:
    """Validate the archive and decompress only the requested built file."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise InvalidDeckArchive("Archive exceeds the size limit")
    normalized = _validate_path(path)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = _validate_archive(archive)
            try:
                return _read_entry(archive, entries[normalized], normalized)
            except KeyError:
                raise InvalidDeckArchive("Deck file unavailable") from None
    except InvalidDeckArchive:
        raise
    except (
        zipfile.BadZipFile,
        EOFError,
        OSError,
        RuntimeError,
        NotImplementedError,
        lzma.LZMAError,
        zlib.error,
    ) as exc:
        raise InvalidDeckArchive("Invalid deck archive") from exc
