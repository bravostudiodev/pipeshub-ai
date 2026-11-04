"""The sandbox Slidev build helper must emit a self-contained dist/index.html."""

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

from app.services.artifact_registry.deck_archive import read_deck_archive

ROOT = Path(__file__).resolve().parents[6]
_SPEC = importlib.util.spec_from_file_location(
    "slidev_build_deck", ROOT / "deployment/sandbox/slidev/build_deck.py"
)
build_deck = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = build_deck
_SPEC.loader.exec_module(build_deck)

INDEX = """<!DOCTYPE html><html><head>
<link rel="preload" as="image" href="./logo.svg">
<script type="module" crossorigin src="./assets/index-abc.js"></script>
<link rel="modulepreload" crossorigin href="./assets/index-abc.js">
<link rel="stylesheet" crossorigin href="./assets/style-abc.css">
</head><body><div id="app"></div></body></html>"""

# Minified Slidev output quotes with backticks and resolves assets from the chunk.
JS = (
    "const a=`/logo.svg`,b=''+new URL(`../logo.svg`,import.meta.url).href,"
    "c=\"./fonts/inter.woff2\",d='</script>',e=`/missing.png`;"
)
CSS = "@font-face{src:url(../fonts/inter.woff2)}.x{background:url('/logo.svg')}"


def _dist(tmp_path: Path, *, index: str = INDEX, js: str = JS) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "fonts").mkdir()
    (dist / "index.html").write_text(index)
    (dist / "assets/index-abc.js").write_text(js)
    (dist / "assets/style-abc.css").write_text(CSS)
    (dist / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (dist / "fonts/inter.woff2").write_bytes(b"wOF2")
    (dist / "_redirects").write_text("/* /index.html 200")
    return dist


def test_inlines_scripts_styles_and_every_asset_reference(tmp_path: Path) -> None:
    html, warnings = build_deck.inline_dist(_dist(tmp_path))

    assert "assets/" not in html
    assert "logo.svg" not in html and "inter.woff2" not in html
    assert html.count("data:image/svg+xml;base64,") == 3
    assert html.count("data:font/woff2;base64,") == 2
    assert '<script type="module">' in html and "<\\/script>" in html
    assert "modulepreload" not in html and 'rel="preload"' not in html
    # A path that matches no built file is reported, not silently dropped.
    assert warnings == ["/missing.png"]


def test_rejects_html_that_still_points_at_another_file(tmp_path: Path) -> None:
    index = INDEX.replace('<div id="app">', '<img src="./missing.png"><div id="app">')
    with pytest.raises(build_deck.DeckBuildError, match="missing.png"):
        build_deck.inline_dist(_dist(tmp_path, index=index))


def test_rejects_split_builds(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    (dist / "assets/md-slide1.js").write_text("export default 1")
    with pytest.raises(build_deck.DeckBuildError, match="code splitting"):
        build_deck.inline_dist(dist)


def test_zip_holds_source_and_a_preview_ready_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "deck"
    (project / "public").mkdir(parents=True)
    (project / "node_modules").mkdir()
    (project / "slides.md").write_text("# Hello")
    (project / "style.css").write_text(":root{--brand:red}")
    (project / "public/logo.svg").write_text("<svg/>")
    (project / "node_modules/junk.js").write_text("x")

    def fake_slidev(work: Path) -> None:
        _dist(work)

    monkeypatch.setattr(build_deck, "_run_slidev", fake_slidev)
    output = tmp_path / "out/deck.zip"
    build_deck.build_deck(project, output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert names == {"dist/index.html", "slides.md", "style.css", "public/logo.svg", "README.md"}
    files = read_deck_archive(output.read_bytes())
    assert set(files) == {"index.html"}


def test_refuses_a_project_vite_config(tmp_path: Path) -> None:
    (tmp_path / "slides.md").write_text("# Hi")
    (tmp_path / "vite.config.ts").write_text("export default {}")
    with pytest.raises(build_deck.DeckBuildError, match="vite.config"):
        build_deck.build_deck(tmp_path, tmp_path / "out.zip")
