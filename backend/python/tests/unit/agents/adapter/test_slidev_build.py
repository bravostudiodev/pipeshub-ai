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
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: ([], 1))
    output, _ = build_deck.build_deck(project, tmp_path / "out/deck.zip")

    assert output == tmp_path / "out/Hello.zip"
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert names == {"dist/index.html", "slides.md", "style.css", "public/logo.svg", "README.md"}
    files = read_deck_archive(output.read_bytes())
    assert set(files) == {"index.html"}


def test_content_right_after_a_separator_starts_a_new_slide() -> None:
    deck = (
        "---\ntheme: default\ntitle: Deck\n---\n\n# Cover\n\n"
        "---\n<!-- 2 -->\n<div>Two</div>\n\n"
        "---\nlayout: center\n---\n\n# Three\n\n"
        "---\n# Four\n\n"
        "```md\n---\n<!-- not a slide -->\n```\n"
    )
    fixed, count = build_deck.separate_slides(deck)

    assert count == 2
    assert "---\n\n<!-- 2 -->" in fixed
    assert "---\n\n# Four" in fixed
    assert "---\nlayout: center\n---" in fixed
    assert "---\n<!-- not a slide -->" in fixed
    assert fixed.startswith("---\ntheme: default\ntitle: Deck\n---\n")


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
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: (['Slide 13: "Research" overlaps "Jeeves QA"'], 1))
    with pytest.raises(build_deck.DeckBuildError, match='Slide 13: "Research" overlaps'):
        build_deck.build_deck(project, tmp_path / "deck.zip")
    assert not list(tmp_path.glob("*.zip"))


def test_an_unverifiable_deck_is_not_delivered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr(build_deck.shutil, "which", lambda name: None)
    with pytest.raises(build_deck.DeckBuildError, match="could not be verified in a browser"):
        build_deck.build_deck(project, tmp_path / "deck.zip")
    assert not list(tmp_path.glob("*.zip"))


def test_a_build_that_loses_slides_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path, monkeypatch)
    (project / "slides.md").write_text("---\ntitle: x\n---\n\n# One\n\n---\n\n# Two\n\n---\nhide: true\n---\n\n# Hidden\n")
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: ([], 1))
    with pytest.raises(build_deck.DeckBuildError, match="defines 2 slides but the build rendered 1"):
        build_deck.build_deck(project, tmp_path / "deck.zip")


def test_count_slides_matches_slidev_rules() -> None:
    deck = (
        "---\ntheme: default\n---\n\n# One\n\n---\nlayout: center\n---\n\n# Two\n\n"
        "---\n\n```md\n---\n---\n```\n\n---\ndisabled: true\n---\n\n# Off\n\n---\n\n# Four\n"
    )
    assert build_deck.count_slides(deck) == 4
    assert build_deck.count_slides("# Only slide, no headmatter\n") == 1


def test_brand_fingerprints_recognise_both_variants(tmp_path: Path) -> None:
    (tmp_path / "OB_Black_Logo.svg").write_text("<svg>\n  <path d='M0 0'/>\n</svg>")
    (tmp_path / "OB_White_Icon.png").write_bytes(b"\x89PNG" + bytes(200))
    (tmp_path / "Sticker-HB.png").write_bytes(b"\x89PNG")
    prints = build_deck.brand_fingerprints(tmp_path)
    assert prints["svg"] == {"<svg><pathd='M00'/></svg>": "OB_Black_Logo"}
    assert list(prints["png"].values()) == ["OB_White_Icon"]


def test_browser_report_is_described_per_slide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [
        {"slide": 13, "kind": "outside", "text": "Research deck", "side": "bottom", "px": 140},
        {"slide": 13, "kind": "outside", "text": "Research deck", "side": "bottom", "px": 140},
        {"slide": 4, "kind": "clipped", "text": "Long card", "px": 30},
        {"slide": 13, "kind": "overlap", "text": "Aleksandar", "other": "Jeeves QA"},
        {"slide": 2, "kind": "contrast", "text": "Subtitle", "ratio": 1.2},
        {"slide": 1, "kind": "logo", "variant": "black", "background": "dark"},
        {"slide": 5, "kind": "image", "text": "hero", "pct": 40},
        {"slide": 1, "kind": "logo", "asset": "OB_Black_Primary_Logo", "variant": "black", "background": "dark"},
        {"slide": 1, "kind": "logo-accent", "asset": "OB_White_Primary_Logo"},
        {"slide": 1, "kind": "logo-size", "asset": "OB_White_Logo", "pct": 92, "limit": 35, "px": 343},
    ]
    dom = '<pre id="oddjeeves-layout-report">' + html.escape(json.dumps({"slides": 14, "issues": issues})) + "</pre>"
    browser = tmp_path / "chromium"
    browser.write_text(f"#!/bin/sh\ncat <<'EOF'\n{dom}\nEOF\n")
    browser.chmod(0o755)
    monkeypatch.setattr(build_deck.shutil, "which", lambda name: str(browser))

    problems, rendered = build_deck.check_layout("<html><body></body></html>", tmp_path)
    assert rendered == 14
    assert problems == [
        'Slide 13: "Research deck" extends 140px past the bottom edge of the slide',
        'Slide 4: "Long card" is cut off by 30px because its box is too small',
        'Slide 13: "Aleksandar" overlaps "Jeeves QA"',
        'Slide 2: "Subtitle" has 1.2:1 contrast with its background; at least 3:1 is required '
        '(text must never be the same colour as what is behind it)',
        "Slide 1: the black OddBytes logo sits on a dark background; use the white variant there "
        "(black artwork on light backgrounds, white on dark or red)",
        'Slide 5: image "hero" has 40% of its area outside the slide',
        "Slide 1: the black OddBytes logo sits on a dark background; use the white variant there "
        "(OB_White_Primary_Logo.svg) (black artwork on light backgrounds, white on dark or red)",
        "Slide 1: OB_White_Primary_Logo has an orange-red accent that disappears against this red background; "
        "use the monochrome OB_White_Logo.svg on red",
        "Slide 1: the OddBytes logo spans 92% of the slide width; keep it under 35% (about 343px wide) "
        "so the title leads, for example a small logo in a corner",
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
<div class="print-slide-container" id="004-01" style="width: 980px; height: 552px; background: #212121">
  <p style="color: #2a2a2a; position: absolute; top: 40px">Nearly invisible</p>
  <p style="color: #FC4539; position: absolute; top: 120px">Red on black is fine</p>
  <img alt="black logo" src="BLACK_LOGO" style="position: absolute; top: 200px; width: 100px">
  <div style="position: absolute; top: 320px; background: #ffffff; padding: 20px"><img alt="white logo" src="WHITE_LOGO" style="width: 100px"></div>
  <img alt="hero" src="BLACK_LOGO" style="position: absolute; left: 900px; top: 400px; width: 200px">
</div>
<div class="print-slide-container" id="005-01" style="width: 980px; height: 552px; background: #FC4539">
  <img alt="cover logo" src="PRIMARY_LOGO" style="position: absolute; left: 40px; top: 40px; width: 900px; height: 120px">
</div>
<div class="print-slide-container" id="006-01" style="width: 980px; height: 552px; background: #FC4539">
  <img alt="corner logo" src="WHITE_LOGO" style="position: absolute; left: 40px; top: 40px; width: 180px">
</div>
</body></html>"""

BLACK_SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M0 0h10v10z' fill='#000'/></svg>"
WHITE_SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M0 0h10v10z' fill='#fff'/></svg>"
PRIMARY_SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M0 0h10v10z' fill='#fff'/><circle r='2' fill='#FD533C'/></svg>"


@pytest.mark.skipif(
    not any(shutil.which(name) for name in build_deck.BROWSERS), reason="needs a local Chromium"
)
def test_layout_check_script_finds_overflow_clipping_and_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    brand = tmp_path / "brand"
    brand.mkdir()
    (brand / "OB_Black_Logo.svg").write_text(BLACK_SVG)
    (brand / "OB_White_Logo.svg").write_text(WHITE_SVG)
    (brand / "OB_White_Primary_Logo.svg").write_text(PRIMARY_SVG)
    monkeypatch.setattr(build_deck, "BRAND_DIR", brand)
    page = PRINT_VIEW.replace(
        "BLACK_LOGO", "data:image/svg+xml;base64," + base64.b64encode(BLACK_SVG.encode()).decode()
    ).replace("WHITE_LOGO", "data:image/svg+xml," + WHITE_SVG.replace("#", "%23").replace("'", "%27")).replace(
        "PRIMARY_LOGO", "data:image/svg+xml;base64," + base64.b64encode(PRIMARY_SVG.encode()).decode()
    )

    problems, rendered = build_deck.check_layout(page, tmp_path)
    assert rendered == 6

    assert not any(problem.startswith("Slide 1:") for problem in problems)
    assert any(problem.startswith('Slide 2: "Row six" extends') and "bottom edge" in problem for problem in problems)
    assert 'Slide 2: "Row five" overlaps "Jeeves QA"' in problems
    assert any(problem.startswith('Slide 3: "First line') and "is cut off" in problem for problem in problems)
    assert not any("decorative numeral" in problem or '"13"' in problem for problem in problems)
    assert 'Slide 4: "Nearly invisible" has 1.1:1 contrast' in "\n".join(problems)
    assert not any("Red on black" in problem for problem in problems)
    assert "Slide 4: the black OddBytes logo sits on a dark background" in "\n".join(problems)
    assert "Slide 4: the white OddBytes logo sits on a light background" in "\n".join(problems)
    assert any(problem.startswith('Slide 4: image "hero" has') for problem in problems)
    assert "Slide 5: OB_White_Primary_Logo has an orange-red accent" in "\n".join(problems)
    assert "Slide 5: the OddBytes logo spans 92% of the slide width" in "\n".join(problems)
    assert not any(problem.startswith("Slide 6:") for problem in problems)
    assert len(problems) == 9, problems


def test_deck_title_prefers_headmatter_then_first_heading() -> None:
    assert build_deck.deck_title("---\ntheme: default\ntitle: 'Q4 OKR Review'\n---\n\n# Cover\n") == "Q4 OKR Review"
    assert build_deck.deck_title("```md\n# not this\n```\n\n# **OddBytes** <span>Q4</span>\n") == "OddBytes Q4"
    assert build_deck.deck_title("no heading at all") is None


def test_zip_name_is_readable_and_safe() -> None:
    assert build_deck.zip_name("Q4 / OKRs: Review?", "fallback") == "Q4 OKRs Review.zip"
    assert build_deck.zip_name("   ", "slidev-presentation") == "slidev-presentation.zip"
    assert build_deck.zip_name("x" * 200, "f") == "x" * build_deck.MAX_NAME_CHARS + ".zip"


def test_rebuilds_keep_the_first_name_even_if_the_title_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One deck stays one artifact: a renamed title or another requested file
    name must not start a second card."""
    project = _project(tmp_path, monkeypatch)
    (project / "slides.md").write_text("---\ntitle: Q4 Review\n---\n\n# Cover\n")
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: ([], 1))
    first, _ = build_deck.build_deck(project, tmp_path / "out/slidev-presentation.zip")

    (project / "slides.md").write_text("---\ntitle: Q4 Review (final)\n---\n\n# Cover\n")
    second, _ = build_deck.build_deck(project, tmp_path / "out/q4-deck.zip")

    assert first == second == tmp_path / "out/Q4 Review.zip"
    with zipfile.ZipFile(second) as archive:
        assert build_deck.DECK_STATE not in archive.namelist()


def test_a_failed_build_still_saves_the_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path, monkeypatch)
    (project / "style.css").write_text(":root{}")
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: (['Slide 1: "x" overlaps "y"'], 1))
    with pytest.raises(build_deck.DeckBuildError):
        build_deck.build_deck(project, tmp_path / "deck.zip")

    with zipfile.ZipFile(tmp_path / build_deck.DRAFT_PATH) as draft:
        assert set(draft.namelist()) == {"slides.md", "style.css", build_deck.DECK_STATE}


def test_main_prints_the_path_it_actually_wrote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setattr(build_deck, "check_layout", lambda html, work: ([], 1))
    assert build_deck.main(["build_deck.py", str(project), str(tmp_path / "requested.zip")]) == 0
    assert f"Wrote {tmp_path / 'Hello.zip'}" in capsys.readouterr().out
