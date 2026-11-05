"""Deck archive validation never extracts or trusts archive-provided MIME types."""

import io
import stat
import zipfile

import pytest

from app.services.artifact_registry.deck_archive import (
    DeckArchiveCache,
    InvalidDeckArchive,
    get_cached_deck_file_async,
    read_deck_archive,
)


def make_zip(entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def test_reads_only_deck_assets_with_explicit_content_types() -> None:
    deck = read_deck_archive(
        make_zip(
            [
                ("slides.md", b"source"),
                ("dist/index.html", b"<html></html>"),
                ("dist/assets/main.js", b"console.log(1)"),
                ("dist/assets/logo.svg", b"<svg/>"),
            ]
        )
    )
    assert set(deck) == {"index.html", "assets/main.js", "assets/logo.svg"}
    assert deck["assets/main.js"].content_type == "text/javascript; charset=utf-8"
    assert deck["assets/logo.svg"].content == b"<svg/>"


@pytest.mark.parametrize(
    "name",
    ["../outside", "dist/../outside.js", "/dist/index.html", "dist/a\\b.js", "C:/bad"],
)
def test_rejects_unsafe_paths_even_outside_dist(name: str) -> None:
    with pytest.raises(InvalidDeckArchive):
        read_deck_archive(make_zip([("dist/index.html", b"ok"), (name, b"x")]))


def test_rejects_symlinks() -> None:
    entry = zipfile.ZipInfo("dist/escape.js")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(InvalidDeckArchive):
        read_deck_archive(
            make_zip([("dist/index.html", b"ok"), (entry, b"/etc/passwd")])
        )


def test_rejects_missing_index_and_unknown_asset_type() -> None:
    with pytest.raises(InvalidDeckArchive):
        read_deck_archive(make_zip([("slides.md", b"source")]))
    deck = read_deck_archive(
        make_zip([("dist/index.html", b"ok"), ("dist/file.customasset", b"x")])
    )
    assert deck["file.customasset"].content_type == "application/octet-stream"


def test_injects_opaque_origin_storage_shim_and_serves_requested_file() -> None:
    from app.services.artifact_registry.deck_archive import get_deck_file

    data = make_zip(
        [
            ("dist/index.html", b"<html><head></head><body></body></html>"),
            ("dist/theme.css", b"body { color: red }"),
        ]
    )
    index = get_deck_file(data, "index.html")
    assert index.content_type == "text/html; charset=utf-8"
    assert b"Object.defineProperty(window,key" in index.content
    assert b"key:.ArrowRight." in index.content or b"ArrowRight" in index.content
    assert (
        index.content.index(b"<head>")
        < index.content.index(b"Object.defineProperty")
        < index.content.index(b"</head>")
    )
    assert get_deck_file(data, "theme.css").content == b"body { color: red }"
    with pytest.raises(InvalidDeckArchive):
        get_deck_file(data, "../index.html")


def test_rejects_duplicate_paths() -> None:
    with pytest.warns(UserWarning), pytest.raises(InvalidDeckArchive):
        read_deck_archive(
            make_zip([("dist/index.html", b"a"), ("dist/index.html", b"b")])
        )


@pytest.mark.asyncio
async def test_cache_reuses_files_only_within_exact_user_version_and_hash() -> None:
    data = make_zip(
        [("dist/index.html", b"<html></html>"), ("dist/theme.css", b"body{}")]
    )
    cache = DeckArchiveCache(max_bytes=1024)
    calls = 0

    async def load() -> dict:
        nonlocal calls
        calls += 1
        return read_deck_archive(data)

    first_key = ("org", "user-a", "artifact", 1, "hash-a")
    assert (
        await get_cached_deck_file_async(cache, first_key, "index.html", load)
    ).content
    assert (
        await get_cached_deck_file_async(cache, first_key, "theme.css", load)
    ).content == b"body{}"
    assert calls == 1
    await get_cached_deck_file_async(
        cache, ("org", "user-b", "artifact", 1, "hash-a"), "index.html", load
    )
    await get_cached_deck_file_async(
        cache, ("org", "user-a", "artifact", 2, "hash-b"), "index.html", load
    )
    assert calls == 3


def test_enforces_archive_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.artifact_registry.deck_archive as module

    data = make_zip([("dist/index.html", b"hello")])
    monkeypatch.setattr(module, "MAX_MEMBER_BYTES", 4)
    with pytest.raises(InvalidDeckArchive):
        read_deck_archive(data)
    monkeypatch.setattr(module, "MAX_MEMBER_BYTES", 100)
    monkeypatch.setattr(module, "MAX_EXTRACTED_BYTES", 4)
    with pytest.raises(InvalidDeckArchive):
        read_deck_archive(data)
    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(InvalidDeckArchive):
        read_deck_archive(data)
