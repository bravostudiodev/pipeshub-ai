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
    pack_version: 1.0.0
---

# Slidev - Presentation Slides for Developers

Web-based slides made from Markdown and built as a static site. Use the
`render_slidev` tool to build the site and receive one ZIP containing the
editable source, static HTML/CSS/JavaScript, included assets, and local
serving instructions.

This fork uses a dedicated offline Docker renderer. Its rules here take
precedence over upstream instructions in the vendored reference, especially
where those describe package installation, network access, development
servers, hosted previews, or browser-based exports. It supports the
preinstalled `default` and `seriph` themes only. Do not create a PPTX or PDF,
install packages, use Playwright, launch a development server, or request a
hosted preview. For a new presentation, always use this skill and
`render_slidev`; do not generate a `.pptx` with `pptxgenjs` or `python-pptx`.
The separate office-utils skill can still edit an existing Office document.

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
---

# First slide

Content here

---

# Second slide

More content
```

Then call `render_slidev` with the Markdown. Add small support files or
authorized existing artifacts for images and local components. Reference
artifacts under `public/input/` and reference them in Markdown without the
`public` prefix, for example `![Chart](/input/chart.svg)`. Supporting files
saved under `public/` are referenced the same way relative to that directory.
The renderer sets a relative base,
hash routing, disables remote asset fetching and CDN font imports, and turns
off export/download controls.

The generated ZIP contains `slides.md`, included source assets, `dist/`, and
`README.md`. The README shows how to serve the site locally. Do not claim the
HTML was visually reviewed unless a separate browser review actually ran.

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

## Quality checklist

1. Give each slide one clear takeaway and vary the layouts.
2. Use concise text and a deliberate, consistent color and type hierarchy.
3. Use the default or seriph theme and local assets only.
4. Use hash navigation and relative references so the exported ZIP works from
   a local HTTP server without rewrite rules.
5. Check that all assets and source files are included in the renderer input.
