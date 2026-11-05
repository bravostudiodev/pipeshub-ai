---
name: slidev
description: Use this skill whenever the user asks for a presentation, slide deck, slides, pitch deck, keynote or talk, for any audience (business, product, sales, training, technical), including requests for a PowerPoint. Builds a polished, animated web slide deck with Slidev in the code sandbox and delivers a ZIP that previews in chat and on share links. Also covers code walkthroughs, Mermaid diagrams, and presenter notes.
license: MIT
metadata:
  agent-loop:
    version: 1.0.0
    category: documents
    subcategory: presentations
    tags: [slides, slidev, presentation, web]
    status: active
    source: builtin
    pack_name: slidev
    pack_version: 1.0.12
---

# Slidev - Presentation Slides for Developers

Web-based slides made from Markdown and built as a static site. Use `run_code`
with the preinstalled Slidev tools in the Docker coding sandbox. Deliver one
ZIP, produced by the build helper below, containing the editable source and a
self-contained `dist/index.html` that OddJeeves previews in chat and on share
links and that opens directly in a browser.

These instructions take precedence over upstream references that describe
package installation, network access, development servers, hosted previews,
or browser-based exports. Use only the preinstalled `default` and `seriph`
themes and local assets. Do not create a PPTX or PDF, install packages, use
Playwright, launch a development server, or request a hosted preview. For a
new presentation, use this skill and `run_code`; the separate office-utils
skill can still edit an existing Office document. Slidev is preinstalled in
the Docker sandbox image; other execution backends may not have it.

## When to use

- Technical presentations and code walkthroughs
- Syntax-highlighted code, click animations, and presenter notes
- Mermaid diagrams and mathematical equations
- A browser presentation the user can preview in chat, share, or open offline

## Quick start

Write complete Slidev Markdown, with `---` separating slides:

```md
---
theme: default
title: My Presentation
base: ./
routerMode: hash
remoteAssets: false
fonts:
  provider: none
download: false
favicon: ""
---

# First slide

Content here

---

# Second slide

More content
```

Always leave a blank line after each `---` slide separator. Text directly
after `---` is read as that slide's frontmatter, which silently merges two
slides into one (the helper repairs this, but write it correctly).

Use `run_code` with Python and `timeout: 600` (calls that run the build helper
always get at least 600 seconds). Create
the project folder in the working directory (`deck/`), never inside
`$OUTPUT_DIR`: every file under `$OUTPUT_DIR` is delivered as its own artifact,
so source files, fonts, and logos placed there appear as separate downloads
and the helper refuses to build such a project. Only the finished ZIP goes in
`$OUTPUT_DIR`. Write
`slides.md`, `style.css`, any Vue components under `components/`, and assets
under `public/` into a project directory, then build it with the preinstalled
helper. Do not write your own build, bundling, or ZIP code, do not add a
`vite.config` file, and do not run `slidev build` directly:

```python
from pathlib import Path
import os, subprocess

project = Path('deck')
(project / 'public').mkdir(parents=True, exist_ok=True)
# Write project / 'slides.md', project / 'style.css' and any public/ or components/ files here.
subprocess.run(['python3', '/opt/slidev/build_deck.py', str(project),
                str(Path(os.environ['OUTPUT_DIR']) / 'slidev-presentation.zip')], check=True)
```

The helper builds the deck and embeds all JavaScript, CSS, fonts, and images
into `dist/index.html`. The preview cannot load separate files, so the helper
fails with an explanation if anything still points at one; fix the source and
run it again rather than working around it. Name the ZIP after the deck when
useful (for example `quarterly-review.zip`), and keep that exact filename for
every rebuild in the conversation: artifacts are versioned by filename, so a
rebuild under a different name (`x.zip` then `x-deck.zip`) shows up as a second,
duplicate artifact instead of a new version. Pass any warnings it prints about
unmatched image paths on to your fixes: they mean an image will not show.

Each successful run writes a new artifact version the user sees, and the
helper only writes the ZIP after its checks pass. Fix problems in the source
and rebuild until it succeeds; do not rebuild afterwards for small polish, and
do not save extra copies, drafts, or PNG exports into `$OUTPUT_DIR`.

The helper also opens every slide in headless Chromium with all clicks
revealed and refuses to deliver the deck if:

- any text runs off the slide, is cut off by its box, or overlaps other text;
- any text has less than 3:1 contrast with the colour behind it (text in the
  same or nearly the same colour as its background);
- an OddBytes logo variant does not suit its background (black artwork belongs
  on light backgrounds; white artwork on dark or red ones);
- an image has more than 10% of its area outside the slide;
- the build rendered fewer slides than `slides.md` defines.

The error names the slide and the element. Fix the source and run the helper
again; there is no way to deliver a deck from a failed build, so never claim
one was produced.

## Layout: everything must fit the slide

Each slide is a fixed canvas of about 980 x 552 px. Nothing scrolls, so content
that does not fit is cut off or runs under the footer. Plan for the slide with
every click revealed:

- Keep each slide to one title plus at most about 40 words of body text, or at
  most 4 rows, cards, or bullets, or 2 short columns. Split anything larger
  across slides (for example "Action items (1/2)" and "(2/2)").
- Keep titles to one line of about 6 words on content slides, at 40-56 px.
  Reserve larger type for cover and section slides.
- Reserve room for the footer. Give content slides a grid layout such as
  `display: grid; grid-template-rows: auto 1fr auto; height: 100%` with the
  footer in the last row, or bottom padding of at least the footer's height
  plus 24 px.
- Do not give text boxes fixed heights, and do not hide overflow with
  `overflow: hidden`; the check still reports clipped text. Fix it by
  splitting or shortening content, not by shrinking body text below 16 px.
- Add `data-layout-ignore` only to a deliberate decorative overlap, such as a
  large background numeral behind a title, never to real content.

## Colour and logo rules

- Decide each slide's background first, then choose every text colour against
  it: dark text (`#212121`) on white, sand or light grey; white text on black,
  dark grey or brand red (`#FC4539`). Never reuse a dark-slide text colour on a
  light slide or the reverse.
- Captions, footers and notes use the same rule; "subtle" grey text must still
  reach 3:1 contrast (on white, no lighter than `#767676`).
- Use `OB_Black_*` logos and icons only on light backgrounds and `OB_White_*`
  only on dark or red backgrounds. A footer component that appears on every
  slide must pick the variant from that slide's background (for example a
  `dark` prop), not use one file everywhere.

## Styling: global CSS goes in `style.css`

Slidev scopes every `<style>` block inside `slides.md` to the single slide that
contains it. A `:root { --brand: ... }` or a reusable class declared there
compiles to a selector that never matches, so colors, backgrounds and fonts
silently disappear from the built deck. Put all deck-wide CSS (custom
properties, `@font-face`, shared classes, layout overrides) in
`deck/style.css`; Slidev loads that file globally. Use a `<style>` block in
`slides.md` only for a rule that must affect one slide. Reference files in
`public/` by absolute paths such as `/fonts/Inter-Regular.otf` or
`/logo/name.svg`; the build rewrites them for the relative base.

```css
/* deck/style.css */
:root { --brand: #FC4539; --ink: #212121; }
.cover { position: absolute; inset: 0; background: var(--brand); color: #fff; padding: 56px 64px; }
.card { background: #F3F3F3; padding: 22px 24px; }
```


Pass existing artifacts via `run_code`'s `input_artifacts`; they are staged at
`input/artifacts/<name>`. Copy needed files into `deck/public/input/` and refer
to them as `/input/<name>` in the Markdown. Include local components and other
support files in the ZIP. Keep the headmatter's relative base, hash routing,
remote-asset/font and download settings above. Do not claim the HTML was
visually reviewed unless a separate browser review actually ran.

## Optional OddBytes brand assets

When the user requests OddBytes branding, follow their design-system skill.
The Docker sandbox includes the Inter typeface (`fc-list | grep -i Inter`) and
the ready-to-use OddBytes logos, icons, and stickers under
`/opt/brand-assets/oddbytes/`. Read that directory's `README.md` for the exact
SVG and transparent PNG filenames; no SVG repair or raster conversion is needed.
Use the black/white primary or monochrome variants as appropriate to the background, following the design-system skill.
The brand guide says to use the icon near the company name, not as a replacement
for the full logo. Use stickers sparingly. Do not apply OddBytes branding to
unrelated presentations by default.

For a self-contained browser deck, copy the selected Inter font files into
`deck/public/fonts/` and declare them with `@font-face` in `deck/style.css`
(not in a `<style>` block in `slides.md`), e.g.
`src: url('/fonts/Inter-Regular.otf') format('opentype')`. Include the font license
from `/usr/share/doc/fonts-inter/copyright` in the ZIP. Copy selected logos,
icons, and stickers into `public/` so they are included in the ZIP and build. The accent font
The Youngest is not installed; do not fetch it over the network or claim it is
available. Do not replace the supplied brand icons with lookalikes.

## Source and references

This skill is adapted from the upstream Slidev skill at
[`slidevjs/slidev/skills/slidev`](https://github.com/slidevjs/slidev/tree/a42aff28dd75f26eb5abbf3d616ea022c3d08924/skills/slidev),
commit `a42aff28dd75f26eb5abbf3d616ea022c3d08924` (2026-10-23). Its original
skill text is available in [upstream.md](upstream.md), and all 53 Markdown
files linked from that skill are vendored in `references/upstream/`. The
upstream MIT license is included in `LICENSE`. Full upstream docs remain at
[`sli.dev`](https://sli.dev).

- [Markdown syntax](references/core-syntax.md)
- [Headmatter and offline settings](references/core-headmatter.md)
- [Animations](references/core-animations.md)
- [Components](references/core-components.md)
- [Layouts](references/core-layouts.md)
- [CLI commands](references/core-cli.md)
- [Static hosting](references/core-hosting.md)

## Presentation design and motion

Create a polished, presentation-ready deck rather than a sequence of plain
bullet lists. Plan a coherent visual story with a strong opening, clear section
changes, and an appropriate closing. Give each slide one clear takeaway and
vary layouts while keeping typography, spacing, and colors consistent. Use
concise text, generous whitespace, readable contrast and type sizes, and
relevant visuals, diagrams, or charts when they help explain the content.
Follow the user's design-system skill when applicable.

Motion should make the deck feel alive and guide attention, not decorate.
Use all three layers below, consistently, on most content slides. Consult the
local [animation reference](references/core-animations.md) for more syntax.

**1. Slide transitions.** Set a deck-wide transition in the headmatter, for
example `transition: slide-left | slide-right` (forward | back), and give
section dividers or the closing slide a different one in their frontmatter
(`transition: fade` or `slide-up`).

**2. Entrance animations.** Animate a slide's key elements in when it opens,
staggered so the eye follows the hierarchy: title first, then supporting text,
then cards or visuals. Use `v-motion` with increasing delays:

```html
<h1 v-motion :initial="{ y: 30, opacity: 0 }"
    :enter="{ y: 0, opacity: 1, transition: { duration: 500 } }">Title</h1>
<p v-motion :initial="{ y: 30, opacity: 0 }"
   :enter="{ y: 0, opacity: 1, transition: { delay: 150, duration: 500 } }">Subtitle</p>
<div v-motion :initial="{ x: -60, opacity: 0 }"
     :enter="{ x: 0, opacity: 1, transition: { delay: 300, duration: 500 } }">Card</div>
```

Vary the direction by role (titles rise, side panels slide in from their side,
stats or images scale up from `scale: 0.9`) and keep durations around
400-700 ms with delays of 100-200 ms between elements.

**3. Click reveals with movement.** Use `v-click` / `v-clicks` to build up
lists, cards, and comparisons point by point, and `v-click` with `v-mark` to
underline, circle, or highlight a key phrase when the speaker reaches it
(`<span v-mark.underline.red="2">key phrase</span>`). Make reveals move as well
as fade by putting this in `style.css` (it also respects reduced-motion
settings):

```css
.slidev-vclick-target { transition: opacity 450ms ease, transform 450ms ease; }
.slidev-vclick-hidden { opacity: 0; transform: translateY(18px); }
@media (prefers-reduced-motion: reduce) {
  .slidev-vclick-target { transition: none; }
  .slidev-vclick-hidden { transform: none; }
}
```

Animate a few meaningful elements per slide rather than every line, and keep
the cover and closing slides calm but not static (a staggered entrance of
logo, title, and subtitle works well). The deck must remain readable with
animation disabled.

## Quality checklist

1. Give each slide one clear takeaway, a deliberate hierarchy, and enough whitespace.
2. Vary layouts and use relevant visuals rather than defaulting to bullet lists.
3. Use slide transitions, staggered `v-motion` entrances, and moving click
   reveals on most content slides.
4. Use the default or seriph theme and local assets only.
5. Keep hash navigation and the relative base, and build only with
   `/opt/slidev/build_deck.py`.
6. Check that all assets and source files are included in the project.
7. Keep deck-wide CSS in `style.css`; `<style>` in `slides.md` is per-slide only.
8. Keep every slide within its canvas and clear of the footer with all clicks
   revealed; the helper's layout check must pass.
