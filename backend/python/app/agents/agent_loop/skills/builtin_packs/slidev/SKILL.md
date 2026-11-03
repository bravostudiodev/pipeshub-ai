---
name: slidev
description: Create and present web-based slidedecks for developers using Slidev with Markdown, Vue components, code highlighting, animations, and interactive features. Use when building technical presentations, conference talks, code walkthroughs, teaching materials, or developer decks.
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
    pack_version: 1.0.3
---

# Slidev - Presentation Slides for Developers

Web-based slides made from Markdown and built as a static site. Use `run_code`
with the preinstalled Slidev tools in the Docker coding sandbox. Deliver one
ZIP containing editable source, static HTML/CSS/JavaScript, included assets,
and local serving instructions.

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
- A static browser presentation the user can download and serve locally

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

Use `run_code` with Python and a generous timeout (e.g. 120 seconds). Create a
project under the sandbox working directory, write the Markdown to `slides.md`,
and link the preinstalled dependencies before building. The `node_modules`
directory itself must be writable for Slidev's generated cache; link its
individual entries, not the directory. For example, after writing your
Markdown and any support files into `deck/`:

```python
from pathlib import Path
import os, shutil, subprocess, zipfile

project = Path('deck')
project.mkdir(exist_ok=True)
# Write project / 'slides.md' and any project / 'public' assets here.
modules = project / 'node_modules'
modules.mkdir(exist_ok=True)
for dependency in Path('/opt/slidev/node_modules').iterdir():
    link = modules / dependency.name
    if not link.exists():
        link.symlink_to(dependency, target_is_directory=dependency.is_dir())
subprocess.run(['/opt/slidev/node_modules/.bin/slidev', 'build', 'slides.md',
                '--out', 'dist', '--base', './'], cwd=project, check=True)
shutil.rmtree(modules)  # Don't transfer dependency links and build caches back.
(project / 'README.md').write_text(
    'Serve locally: python3 -m http.server 8000 --directory dist\n'
    'Then open http://localhost:8000/. The source is slides.md.\n'
)
with zipfile.ZipFile(Path(os.environ['OUTPUT_DIR']) / 'slidev-presentation.zip', 'w',
                     zipfile.ZIP_DEFLATED) as archive:
    for path in project.rglob('*'):
        if path.is_file() and 'node_modules' not in path.parts:
            archive.write(path, path.relative_to(project))
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

For a self-contained browser deck, copy the selected Inter font files into the
project and declare them with CSS `@font-face` using paths relative to the CSS;
the build must bundle or copy the files into `dist/`. Include the font license
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

Use tasteful, consistent slide transitions and click-triggered reveals where
they improve pacing or understanding. Prefer subtle motion, and avoid
excessive effects, distracting movement, or revealing every line separately.
Ensure the complete content remains readable without relying on animation;
respect reduced-motion preferences where possible. Consult the local
[animation reference](references/core-animations.md) for supported syntax.

## Quality checklist

1. Give each slide one clear takeaway, a deliberate hierarchy, and enough whitespace.
2. Vary layouts and use relevant visuals rather than defaulting to bullet lists.
3. Add purposeful, restrained transitions or reveals where they improve the deck.
4. Use the default or seriph theme and local assets only.
5. Use hash navigation and relative references so the exported ZIP works from
   a local HTTP server without rewrite rules.
6. Check that all assets and source files are included in the project.
