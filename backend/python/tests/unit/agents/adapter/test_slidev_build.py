"""The sandbox Slidev build helper must emit a self-contained dist/index.html."""

import html
import importlib.util
import json
import shutil
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
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: [])
    output = tmp_path / "out/deck.zip"
    build_deck.build_deck(project, output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert names == {"dist/index.html", "slides.md", "style.css", "public/logo.svg", "README.md"}
    files = read_deck_archive(output.read_bytes())
    assert set(files) == {"index.html"}


def test_refuses_a_project_inside_the_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "out"
    project = output_dir / "deck"
    project.mkdir(parents=True)
    (project / "slides.md").write_text("# Hi")
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    with pytest.raises(build_deck.DeckBuildError, match="inside \\$OUTPUT_DIR"):
        build_deck.build_deck(project, output_dir / "deck.zip")


def test_refuses_a_project_vite_config(tmp_path: Path) -> None:
    (tmp_path / "slides.md").write_text("# Hi")
    (tmp_path / "vite.config.ts").write_text("export default {}")
    with pytest.raises(build_deck.DeckBuildError, match="vite.config"):
        build_deck.build_deck(tmp_path, tmp_path / "out.zip")


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "deck"
    project.mkdir()
    (project / "slides.md").write_text("# Hello")
    monkeypatch.setattr(build_deck, "_run_slidev", lambda work: _dist(work))
    return project


def test_layout_problems_fail_the_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: ['Slide 13: "Research" overlaps "Jeeves QA"'])
    output = tmp_path / "deck.zip"
    with pytest.raises(build_deck.DeckBuildError, match='Slide 13: "Research" overlaps'):
        build_deck.build_deck(project, output)
    assert not output.exists()


def test_a_missing_browser_skips_the_layout_check_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr(build_deck.shutil, "which", lambda name: None)
    output = tmp_path / "deck.zip"
    warnings = build_deck.build_deck(project, output)
    assert output.exists()
    assert "layout check skipped: no Chromium browser is installed" in warnings


def test_browser_report_is_described_per_slide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [
        {"slide": 13, "kind": "outside", "text": "Research deck", "side": "bottom", "px": 140},
        {"slide": 13, "kind": "outside", "text": "Research deck", "side": "bottom", "px": 140},
        {"slide": 4, "kind": "clipped", "text": "Long card", "px": 30},
        {"slide": 13, "kind": "overlap", "text": "Aleksandar", "other": "Jeeves QA"},
    ]
    dom = '<pre id="oddjeeves-layout-report">' + html.escape(json.dumps({"slides": 14, "issues": issues})) + "</pre>"
    browser = tmp_path / "chromium"
    browser.write_text(f"#!/bin/sh\ncat <<'EOF'\n{dom}\nEOF\n")
    browser.chmod(0o755)
    monkeypatch.setattr(build_deck.shutil, "which", lambda name: str(browser))

    assert build_deck.check_layout("<html><body></body></html>", tmp_path) == [
        'Slide 13: "Research deck" extends 140px past the bottom edge of the slide',
        'Slide 4: "Long card" is cut off by 30px because its box is too small',
        'Slide 13: "Aleksandar" overlaps "Jeeves QA"',
    ]


# Mimics Slidev's print view: one fixed-size .print-slide-container per slide.
PRINT_VIEW = """<!DOCTYPE html><html><head><style>
body { margin: 0; font: 20px sans-serif; }
.print-slide-container { position: relative; overflow: hidden; width: 980px; height: 552px; }
.footer { position: absolute; left: 40px; bottom: 20px; }
.rows { position: absolute; left: 40px; top: 300px; }
.rows div { height: 50px; }
.card { height: 30px; overflow: hidden; width: 300px; }
</style></head><body>
<div class="print-slide-container" id="001-01" style="width: 980px; height: 552px">
  <h1>Fits</h1><p>Short text</p><div class="footer">Jeeves QA</div>
</div>
<div class="print-slide-container" id="002-01" style="width: 980px; height: 552px">
  <div class="rows"><div>Row one</div><div>Row two</div><div>Row three</div><div>Row four</div><div>Row five</div><div>Row six</div></div>
  <div class="footer">Jeeves QA</div>
</div>
<div class="print-slide-container" id="003-01" style="width: 980px; height: 552px">
  <div class="card">First line<br>Second line hidden by the box</div>
  <div data-layout-ignore style="position: absolute; top: 120px; font-size: 200px">13</div>
  <h1 style="position: absolute; top: 200px">Title over a decorative numeral</h1>
</div>
</body></html>"""


@pytest.mark.skipif(
    not any(shutil.which(name) for name in build_deck.BROWSERS), reason="needs a local Chromium"
)
def test_layout_check_script_finds_overflow_clipping_and_overlap(tmp_path: Path) -> None:
    problems = build_deck.check_layout(PRINT_VIEW, tmp_path)

    assert not any(problem.startswith("Slide 1:") for problem in problems)
    assert any(problem.startswith('Slide 2: "Row six" extends') and "bottom edge" in problem for problem in problems)
    assert 'Slide 2: "Row five" overlaps "Jeeves QA"' in problems
    assert any(problem.startswith('Slide 3: "First line') and "is cut off" in problem for problem in problems)
    assert not any("decorative numeral" in problem or '"13"' in problem for problem in problems)
    assert len(problems) == 3, problems
