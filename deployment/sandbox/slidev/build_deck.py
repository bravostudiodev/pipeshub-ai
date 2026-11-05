"""Build a Slidev project into a ZIP whose dist/index.html is fully self-contained.

Usage: python3 /opt/slidev/build_deck.py <project_dir> <output.zip>

The ZIP is named after the deck's title (the headmatter `title:` or the first
heading), not the name passed in, and keeps that name on every later rebuild,
so a deck stays one artifact with new versions instead of a new card per build.
Every run also saves the project source as a draft beside the project folder
(`.oddjeeves/deck-draft.zip`), pass or fail, so a later message can continue.

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
BRAND_DIR = Path(os.environ.get("BRAND_ASSETS_DIR", "/opt/brand-assets/oddbytes"))
MAX_LAYOUT_ISSUES = 15
# Matches MAX_MEMBER_BYTES in app/services/artifact_registry/deck_archive.py.
MAX_INDEX_BYTES = 20 * 1024 * 1024
DECK_STATE = ".oddjeeves-deck.json"
DRAFT_PATH = Path(".oddjeeves/deck-draft.zip")
MAX_DRAFT_BYTES = 20 * 1024 * 1024
MAX_NAME_CHARS = 80
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
# Per-slide frontmatter starts with a `key:` line; anything else directly after `---` is slide content.
_FRONTMATTER_KEY = re.compile(r"^[A-Za-z_][\w-]*\s*:")
_FENCE = re.compile(r"^\s*(```|~~~)")
_NAME_UNSAFE = re.compile(r"[^\w &()',.\-]+")
_LAYOUT_REPORT = re.compile(r'<pre id="oddjeeves-layout-report">(.*?)</pre>', re.DOTALL)

mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/avif", ".avif")


class DeckBuildError(RuntimeError):
    """The deck cannot be delivered as a self-contained presentation."""


class LayoutCheckUnavailable(RuntimeError):
    """The browser layout check could not run, so the deck cannot be verified."""


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
    kind = issue.get("kind")
    if kind == "outside":
        return f"{where}: \"{text}\" extends {issue.get('px')}px past the {issue.get('side')} edge of the slide"
    if kind == "clipped":
        return f"{where}: \"{text}\" is cut off by {issue.get('px')}px because its box is too small"
    if kind == "contrast":
        return (f"{where}: \"{text}\" has {issue.get('ratio')}:1 contrast with its background; "
                "at least 3:1 is required (text must never be the same colour as what is behind it)")
    if kind == "logo":
        variant = issue.get("variant")
        other = "white" if variant == "black" else "black"
        asset = issue.get("asset")
        swap = ""
        if asset:
            target = asset.replace("OB_Black_", "OB_White_") if variant == "black" else asset.replace("OB_White_", "OB_Black_")
            swap = f" ({target}.svg)"
        return (f"{where}: the {variant} OddBytes logo sits on a {issue.get('background')} background; "
                f"use the {other} variant there{swap} (black artwork on light backgrounds, white on dark or red)")
    if kind == "logo-accent":
        asset = issue.get("asset", "")
        return (f"{where}: {asset} has an orange-red accent that disappears against this red background; "
                f"use the monochrome {asset.replace('_Primary_', '_')}.svg on red")
    if kind == "logo-size":
        what = "icon" if str(issue.get("asset", "")).endswith("_Icon") else "logo"
        return (f"{where}: the OddBytes {what} spans {issue.get('pct')}% of the slide width; keep it under "
                f"{issue.get('limit')}% (about {issue.get('px')}px wide) so the title leads, for example a small "
                f"{what} in a corner")
    if kind == "image":
        return f"{where}: image \"{text}\" has {issue.get('pct')}% of its area outside the slide"
    return f"{where}: \"{text}\" overlaps \"{issue.get('other', '')}\""


def brand_fingerprints(brand_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """Recognisers for the OddBytes logo files once they are inlined as data: URIs.

    SVGs are matched by their whitespace-stripped text (Vite inlines them as
    URL-encoded text, our inliner as base64; both decode to the same file).
    PNGs are matched by the start of their base64 payload.
    """
    brand_dir = brand_dir or BRAND_DIR
    fingerprints: dict[str, dict[str, str]] = {"svg": {}, "png": {}}
    if not brand_dir.is_dir():
        return fingerprints
    for path in brand_dir.iterdir():
        name = path.name
        if not name.startswith(("OB_Black_", "OB_White_")):
            continue
        if path.suffix == ".svg":
            fingerprints["svg"]["".join(path.read_text(encoding="utf-8").split())] = path.stem
        elif path.suffix == ".png":
            fingerprints["png"][base64.b64encode(path.read_bytes()).decode()[:120]] = path.stem
    return fingerprints


def count_slides(markdown: str) -> int:
    """Slides Slidev will render from `slides.md` (hidden/disabled ones excluded)."""
    lines = markdown.split("\n")
    in_fence = False
    index = 0
    if lines and lines[0].strip() == "---":
        index = 1
        while index < len(lines) and lines[index].strip() != "---":
            index += 1
        index += 1
    shown = 1
    hidden = 0
    while index < len(lines):
        line = lines[index]
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.strip() == "---":
            shown += 1
            if index + 1 < len(lines) and _FRONTMATTER_KEY.match(lines[index + 1]):
                index += 1
                frontmatter = []
                while index < len(lines) and lines[index].strip() != "---":
                    frontmatter.append(lines[index].strip())
                    index += 1
                if any(entry.replace(" ", "") in ("hide:true", "disabled:true") for entry in frontmatter):
                    hidden += 1
        index += 1
    return shown - hidden


def check_layout(index_html: str, work: Path) -> tuple[list[str], int]:
    """Render every slide with all clicks revealed; return problems and the slide count."""
    browser = next((path for name in BROWSERS if (path := shutil.which(name))), None)
    if browser is None:
        raise LayoutCheckUnavailable("no Chromium browser is installed")
    brand = json.dumps(brand_fingerprints()).replace("</", "<\\/")
    script = (
        "<script>window.__oddjeevesBrand = " + brand + ";</script>"
        "<script>" + LAYOUT_CHECK.read_text(encoding="utf-8") + "</script>"
    )
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
    return list(dict.fromkeys(_describe(issue) for issue in report.get("issues", []))), int(report["slides"])


def separate_slides(markdown: str) -> tuple[str, int]:
    """Insert a blank line after slide separators that are directly followed by content.

    Slidev reads text right after `---` as that slide's frontmatter, so
    `---\n<!-- 2 -->\n<div>` silently merges two slides into one. Returns the
    fixed text and the number of separators fixed.
    """
    lines = markdown.split("\n")
    output: list[str] = []
    fixed = 0
    in_fence = False
    separators = 0
    for index, line in enumerate(lines):
        output.append(line)
        if _FENCE.match(line):
            in_fence = not in_fence
        if in_fence or line.strip() != "---":
            continue
        separators += 1
        # The first two separators open and close the deck headmatter.
        if separators <= 2 and lines[0].strip() == "---":
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if following.strip() and not _FRONTMATTER_KEY.match(following):
            output.append("")
            fixed += 1
    return "\n".join(output), fixed


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


def deck_title(markdown: str) -> str | None:
    """The headmatter `title:`, else the first `# ` heading outside code fences."""
    lines = markdown.split("\n")
    index = 0
    if lines and lines[0].strip() == "---":
        index = 1
        while index < len(lines) and lines[index].strip() != "---":
            key, _, value = lines[index].partition(":")
            if key.strip() == "title" and value.strip().strip("'\""):
                return value.strip().strip("'\"")
            index += 1
        index += 1
    in_fence = False
    for line in lines[index:]:
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("# "):
            text = re.sub(r"<[^>]+>|[*_`]", "", line[2:]).strip()
            if text:
                return text
    return None


def zip_name(title: str | None, fallback: str) -> str:
    """A readable, filesystem-safe file name for the deck, e.g. `OddBytes Q4 OKRs.zip`."""
    cleaned = re.sub(r"\s+", " ", _NAME_UNSAFE.sub(" ", title or "")).strip(" .")[:MAX_NAME_CHARS].strip(" .")
    return f"{cleaned or fallback}.zip"


def resolve_output(project: Path, requested: Path, markdown: str) -> Path:
    """Where the ZIP goes: the name pinned by an earlier build, else one from the title.

    The name is pinned in the project so every rebuild, including one in a later
    message from the restored draft, updates the same artifact.
    """
    state_path = project / DECK_STATE
    name = None
    try:
        name = json.loads(state_path.read_text(encoding="utf-8")).get("zipName")
    except (OSError, ValueError, AttributeError):
        name = None
    if not isinstance(name, str) or not name.endswith(".zip") or "/" in name or name.startswith("."):
        name = zip_name(deck_title(markdown), requested.stem or "Presentation")
        state_path.write_text(json.dumps({"zipName": name}), encoding="utf-8")
    return requested.parent / name


def save_draft(project: Path) -> Path | None:
    """Snapshot the project source so a later message can restore and continue it."""
    sources = _source_files(project)
    if sum(path.stat().st_size for path in sources) > MAX_DRAFT_BYTES:
        print("Note: the project is too large to save as a draft; drop unused fonts or images.", file=sys.stderr)
        return None
    draft = project.parent / DRAFT_PATH
    try:
        draft.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(draft, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sources:
                archive.write(path, path.relative_to(project).as_posix())
    except OSError as error:
        print(f"Note: the project draft could not be saved ({error}).", file=sys.stderr)
        return None
    return draft


def build_deck(project: Path, output: Path) -> tuple[Path, list[str]]:
    project = project.resolve()
    output_dir = os.environ.get("OUTPUT_DIR")
    if output_dir and project.is_relative_to(Path(output_dir).resolve()):
        raise DeckBuildError(
            f"The project folder {project} is inside $OUTPUT_DIR, so every source file would be "
            "delivered as a separate artifact. Create the project in the working directory "
            "(for example 'deck/') and write only the ZIP to $OUTPUT_DIR."
        )
    if not (project / "slides.md").is_file():
        raise DeckBuildError(f"{project}/slides.md does not exist")
    slides = project / "slides.md"
    fixed_text, fixed = separate_slides(slides.read_text(encoding="utf-8"))
    if fixed:
        slides.write_text(fixed_text, encoding="utf-8")
    output = resolve_output(project, output, fixed_text)
    save_draft(project)
    if any((project / name).exists() for name in ("vite.config.ts", "vite.config.js", "vite.config.mjs")):
        raise DeckBuildError("Remove the project's vite.config file; build_deck.py supplies the build config")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary) / "deck"
        _copy_source(project, work)
        _run_slidev(work)
        html, warnings = inline_dist(work / "dist")
        try:
            problems, rendered = check_layout(html, Path(temporary))
        except LayoutCheckUnavailable as error:
            raise DeckBuildError(
                f"The deck could not be verified in a browser ({error}), so it was not delivered. "
                "This is an environment problem, not a problem with the slides; report it rather than "
                "retrying with different content."
            ) from error
    expected = count_slides(fixed_text)
    if rendered != expected:
        raise DeckBuildError(
            f"slides.md defines {expected} slides but the build rendered {rendered}. Slides are lost when "
            "text follows a `---` separator directly or a separator sits inside unclosed HTML; put a blank "
            "line after every `---` and close every tag."
        )
    if problems:
        shown = "\n".join(f"  - {problem}" for problem in problems[:MAX_LAYOUT_ISSUES])
        more = len(problems) - MAX_LAYOUT_ISSUES
        raise DeckBuildError(
            "The deck was not delivered because some slides are not presentable (checked with every click revealed):\n"
            + shown
            + (f"\n  ... and {more} more" if more > 0 else "")
            + "\nFix every item in one pass, editing the files in this same project folder (split crowded "
            "slides, shorten text, move labels, change colours, or change the logo file or size), then rebuild. "
            "Mark a deliberate decorative overlap with data-layout-ignore."
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
        sources = [path for path in _source_files(project) if path.name != DECK_STATE]
        for path in sources:
            archive.write(path, path.relative_to(project).as_posix())
        if not any(path.relative_to(project).as_posix() == "README.md" for path in sources):
            archive.writestr("README.md", readme)
    return output, warnings


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    try:
        output, warnings = build_deck(Path(argv[1]), Path(argv[2]))
    except DeckBuildError as error:
        print(f"Deck build failed: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Warning: '{warning}' does not match any file in the deck; that image or font will not show.")
    print(f"Wrote {output} ({output.stat().st_size:,} bytes) with a self-contained dist/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
