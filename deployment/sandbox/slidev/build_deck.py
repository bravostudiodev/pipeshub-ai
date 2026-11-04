"""Build a Slidev project into a ZIP whose dist/index.html is fully self-contained.

Usage: python3 /opt/slidev/build_deck.py <project_dir> <output.zip>

OddJeeves previews decks in an opaque-origin sandboxed iframe behind a
zero-trust gateway. Requests made by that iframe carry no gateway cookie, so a
deck that loads separate JS, CSS, font or image files renders blank. This
script builds without code splitting and embeds every remaining file into
dist/index.html, then refuses to write a deck that still references another file.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import mimetypes
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SLIDEV_ROOT = Path(os.environ.get("SLIDEV_ROOT", "/opt/slidev"))
VITE_CONFIG = Path(__file__).with_name("single-file.vite.mjs")
LAYOUT_CHECK = Path(__file__).with_name("layout_check.js")
BROWSERS = ("chromium", "chromium-browser", "google-chrome")
MAX_LAYOUT_ISSUES = 15
# Matches MAX_MEMBER_BYTES in app/services/artifact_registry/deck_archive.py.
MAX_INDEX_BYTES = 20 * 1024 * 1024
SKIPPED_SOURCE_PARTS = {"node_modules", "dist", ".slidev", ".git", "__pycache__"}

# Minified JS quotes strings with backticks, so ` counts alongside " ' and url( ).
_OPEN, _CLOSE = "[\"'`(]", "[\"'`)]"
_ASSET = (
    r"((?:\.{0,2}/)*[\w./@-]+\."
    r"(?:svg|png|jpe?g|gif|webp|avif|ico|otf|ttf|woff2?|mp4|webm|mp3|ogg|wav))"
)
_ASSET_REF = re.compile(f"({_OPEN}){_ASSET}({_CLOSE})", re.IGNORECASE)
_LOCAL_ATTR = re.compile(
    r"""\b(?:src|href)\s*=\s*["'](?!data:|#|https?:|mailto:|javascript:)([^"']+)""",
    re.IGNORECASE,
)
_SCRIPT = re.compile(
    r'<script\b[^>]*\bsrc="\./(assets/[^"]+\.js)"[^>]*>\s*</script>', re.IGNORECASE
)
_STYLESHEET = re.compile(
    r'<link\b[^>]*\brel="stylesheet"[^>]*\bhref="\./(assets/[^"]+\.css)"[^>]*>',
    re.IGNORECASE,
)
_RESOURCE_HINT = re.compile(
    r'<link\b[^>]*\brel="(?:modulepreload|preload|prefetch|icon)"[^>]*>\s*', re.IGNORECASE
)
_LAYOUT_REPORT = re.compile(r'<pre id="oddjeeves-layout-report">(.*?)</pre>', re.DOTALL)

mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/avif", ".avif")


class DeckBuildError(RuntimeError):
    """The deck cannot be delivered as a self-contained presentation."""


class LayoutCheckUnavailable(RuntimeError):
    """The browser layout check could not run; the deck itself may be fine."""


def _data_uris(dist: Path) -> dict[str, str]:
    uris = {}
    for path in dist.rglob("*"):
        relative = path.relative_to(dist).as_posix()
        if path.is_file() and path.suffix not in (".html", ".js", ".css") and path.name != "_redirects":
            mime = mimetypes.guess_type(relative)[0] or "application/octet-stream"
            uris[relative] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    return uris


def _resolve(reference: str, base_dir: str) -> str:
    if reference.startswith("/"):
        return posixpath.normpath(reference.lstrip("/"))
    return posixpath.normpath(posixpath.join(base_dir, reference))


def _embed(text: str, base_dir: str, uris: dict[str, str]) -> str:
    def swap(match: re.Match[str]) -> str:
        uri = uris.get(_resolve(match.group(2), base_dir))
        return match.group(1) + uri + match.group(3) if uri else match.group(0)

    return _ASSET_REF.sub(swap, text)


def inline_dist(dist: Path) -> tuple[str, list[str]]:
    """Return a self-contained index.html and warnings for unresolved asset-like strings."""
    html = (dist / "index.html").read_text(encoding="utf-8")
    uris = _data_uris(dist)

    scripts = _SCRIPT.findall(html)
    if len(scripts) != 1:
        raise DeckBuildError(f"Expected one bundled script in index.html, found {len(scripts)}")
    if any(path.name != scripts[0].split("/")[-1] for path in (dist / "assets").rglob("*.js")):
        raise DeckBuildError("The build produced several JavaScript chunks; code splitting is still enabled")

    def stylesheet(match: re.Match[str]) -> str:
        css = _embed((dist / match.group(1)).read_text(encoding="utf-8"), "assets", uris)
        return "<style>" + css.replace("</style", "<\\/style") + "</style>"

    def script(match: re.Match[str]) -> str:
        js = _embed((dist / match.group(1)).read_text(encoding="utf-8"), "assets", uris)
        # Keep the HTML parser from ending or re-entering the inline script early.
        js = js.replace("</script", "<\\/script").replace("<!--", "<\\!--")
        return '<script type="module">' + js + "</script>"

    html = _STYLESHEET.sub(stylesheet, html)
    html = _SCRIPT.sub(script, html)
    html = _RESOURCE_HINT.sub("", html)
    html = _embed(html, "", uris)

    unresolved = set(_LOCAL_ATTR.findall(html)) | {
        match.group(2)
        for match in _ASSET_REF.finditer(html)
        if _resolve(match.group(2), "assets") in uris or _resolve(match.group(2), "") in uris
    }
    if unresolved:
        raise DeckBuildError("index.html still references other files: " + ", ".join(sorted(unresolved)))
    # Strings that look like files but match nothing built are usually broken
    # image paths in the source; report them without failing the build.
    warnings = sorted({match.group(2) for match in _ASSET_REF.finditer(html)})
    return html, warnings


def _describe(issue: dict) -> str:
    where = f"Slide {issue.get('slide', '?')}"
    text = issue.get("text", "")
    if issue.get("kind") == "outside":
        return f"{where}: \"{text}\" extends {issue.get('px')}px past the {issue.get('side')} edge of the slide"
    if issue.get("kind") == "clipped":
        return f"{where}: \"{text}\" is cut off by {issue.get('px')}px because its box is too small"
    return f"{where}: \"{text}\" overlaps \"{issue.get('other', '')}\""


def check_layout(index_html: str, work: Path) -> list[str]:
    """Render every slide with all clicks revealed and return layout problems."""
    browser = next((path for name in BROWSERS if (path := shutil.which(name))), None)
    if browser is None:
        raise LayoutCheckUnavailable("no Chromium browser is installed")
    script = "<script>" + LAYOUT_CHECK.read_text(encoding="utf-8") + "</script>"
    # The last </body> is the document's; the inlined bundle may contain the string too.
    head, tag, tail = index_html.rpartition("</body>")
    page_html = head + script + tag + tail if tag else index_html + script
    page = work / "layout-check.html"
    page.write_text(page_html, encoding="utf-8")
    try:
        result = subprocess.run(
            [
                browser, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--no-first-run", "--disable-extensions", "--hide-scrollbars", "--mute-audio",
                f"--user-data-dir={work / 'chromium-profile'}", "--window-size=1920,1080",
                "--virtual-time-budget=30000", "--dump-dom", page.as_uri() + "?print#/print",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LayoutCheckUnavailable(f"Chromium did not finish: {error}") from error
    match = _LAYOUT_REPORT.search(result.stdout)
    if match is None:
        detail = result.stderr.strip().splitlines()[-1:] or ["no report"]
        raise LayoutCheckUnavailable(f"Chromium returned no layout report ({detail[0]})")
    try:
        report = json.loads(html_lib.unescape(match.group(1)))
    except ValueError as error:
        raise LayoutCheckUnavailable(f"unreadable layout report: {error}") from error
    if report.get("error") or not report.get("slides"):
        raise LayoutCheckUnavailable(report.get("error") or "the print view rendered no slides")
    return list(dict.fromkeys(_describe(issue) for issue in report.get("issues", [])))


def _copy_source(project: Path, work: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in SKIPPED_SOURCE_PARTS}

    shutil.copytree(project, work, ignore=ignore, symlinks=False)


def _run_slidev(work: Path) -> None:
    modules = work / "node_modules"
    modules.mkdir()
    for dependency in (SLIDEV_ROOT / "node_modules").iterdir():
        (modules / dependency.name).symlink_to(dependency, target_is_directory=dependency.is_dir())
    shutil.copyfile(VITE_CONFIG, work / "vite.config.mjs")
    result = subprocess.run(
        [str(SLIDEV_ROOT / "node_modules/.bin/slidev"), "build", "slides.md", "--out", "dist", "--base", "./"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        log = (result.stdout + result.stderr).strip().splitlines()
        raise DeckBuildError("slidev build failed:\n" + "\n".join(log[-40:]))


def _source_files(project: Path) -> list[Path]:
    return sorted(
        path
        for path in project.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not SKIPPED_SOURCE_PARTS.intersection(path.relative_to(project).parts)
    )


def build_deck(project: Path, output: Path) -> list[str]:
    project = project.resolve()
    if not (project / "slides.md").is_file():
        raise DeckBuildError(f"{project}/slides.md does not exist")
    if any((project / name).exists() for name in ("vite.config.ts", "vite.config.js", "vite.config.mjs")):
        raise DeckBuildError("Remove the project's vite.config file; build_deck.py supplies the build config")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary) / "deck"
        _copy_source(project, work)
        _run_slidev(work)
        html, warnings = inline_dist(work / "dist")
        try:
            problems = check_layout(html, Path(temporary))
        except LayoutCheckUnavailable as error:
            problems = []
            warnings.append(f"layout check skipped: {error}")
    if problems:
        shown = "\n".join(f"  - {problem}" for problem in problems[:MAX_LAYOUT_ISSUES])
        more = len(problems) - MAX_LAYOUT_ISSUES
        raise DeckBuildError(
            "Some slide content does not fit (checked with every click revealed):\n"
            + shown
            + (f"\n  ... and {more} more" if more > 0 else "")
            + "\nSplit crowded slides, shorten text, or shrink type and spacing, then rebuild. "
            "Mark deliberate decorative overlaps with data-layout-ignore."
        )
    index = html.encode("utf-8")
    if len(index) > MAX_INDEX_BYTES:
        raise DeckBuildError(
            f"dist/index.html is {len(index) // (1024 * 1024)} MB; the preview limit is "
            f"{MAX_INDEX_BYTES // (1024 * 1024)} MB. Use fewer or smaller images."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    readme = (
        "Open dist/index.html in a browser; it is self-contained and needs no server.\n"
        "The source is slides.md (plus style.css, components/ and public/ when present).\n"
    )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dist/index.html", index)
        sources = _source_files(project)
        for path in sources:
            archive.write(path, path.relative_to(project).as_posix())
        if not any(path.relative_to(project).as_posix() == "README.md" for path in sources):
            archive.writestr("README.md", readme)
    return warnings


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    try:
        warnings = build_deck(Path(argv[1]), Path(argv[2]))
    except DeckBuildError as error:
        print(f"Deck build failed: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        if warning.startswith("layout check skipped"):
            print(f"Warning: {warning}.")
        else:
            print(f"Warning: '{warning}' does not match any file in the deck; that image or font will not show.")
    print(f"Wrote {argv[2]} ({Path(argv[2]).stat().st_size:,} bytes) with a self-contained dist/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
