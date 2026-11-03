---
name: slidev
description: Create and present web-based slidedecks for developers using Slidev with Markdown, Vue components, code highlighting, animations, and interactive features. Use when building technical presentations, conference talks, code walkthroughs, teaching materials, or developer decks.
---

> Fork note: this is the original upstream skill text, retained for reference.
> The fork-specific `SKILL.md` in this pack governs execution and overrides
> conflicting package-installation, network, hosting, and export guidance.

# Slidev - Presentation Slides for Developers

Web-based slides maker built on Vite, Vue, and Markdown.

## When to Use

- Technical presentations or slidedecks with live code examples
- Syntax-highlighted code snippets with animations
- Interactive demos (Monaco editor, runnable code)
- Mathematical equations (LaTeX) or diagrams (Mermaid, PlantUML)
- Record presentations with presenter notes
- Export to PDF, PPTX, or host as SPA
- Code walkthroughs for developer talks or workshops

## Quick Start

```bash
pnpm create slidev    # Create project
pnpm run dev          # Start dev server (opens http://localhost:3030)
pnpm run build        # Build static SPA
pnpm run export       # Export to PDF (requires playwright-chromium)
```

**Verify**: After `pnpm run dev`, confirm slides load at `http://localhost:3030`. After `pnpm run export`, check the output PDF exists in the project root.

## Basic Syntax

```md
---
theme: default
title: My Presentation
---

# First Slide

Content here

---

# Second Slide

More content

<!--
Presenter notes go here
-->
```

- `---` separates slides
- First frontmatter = headmatter (deck config)
- HTML comments = presenter notes

## Core References

| Topic | Description | Reference |
|-------|-------------|-----------|
| Markdown Syntax | Slide separators, frontmatter, notes, code blocks | [core-syntax](references/upstream/core-syntax.md) |
| Animations | v-click, v-clicks, motion, transitions | [core-animations](references/upstream/core-animations.md) |
| Headmatter | Deck-wide configuration options | [core-headmatter](references/upstream/core-headmatter.md) |
| Frontmatter | Per-slide configuration options | [core-frontmatter](references/upstream/core-frontmatter.md) |
| CLI Commands | Dev, build, export, theme commands | [core-cli](references/upstream/core-cli.md) |
| Components | Built-in Vue components | [core-components](references/upstream/core-components.md) |
| Layouts | Built-in slide layouts | [core-layouts](references/upstream/core-layouts.md) |
| Exporting | PDF, PPTX, PNG export options | [core-exporting](references/upstream/core-exporting.md) |
| Hosting | Build and deploy to various platforms | [core-hosting](references/upstream/core-hosting.md) |
| Global Context | $nav, $slidev, composables API | [core-global-context](references/upstream/core-global-context.md) |

## Feature Reference

### Code & Editor

| Feature | Usage | Reference |
|---------|-------|-----------|
| Line highlighting | `` ```ts {2,3} `` | [code-line-highlighting](references/upstream/code-line-highlighting.md) |
| Click-based highlighting | `` ```ts {1\|2-3\|all} `` | [code-line-highlighting](references/upstream/code-line-highlighting.md) |
| Line numbers | `lineNumbers: true` or `{lines:true}` | [code-line-numbers](references/upstream/code-line-numbers.md) |
| Scrollable code | `{maxHeight:'100px'}` | [code-max-height](references/upstream/code-max-height.md) |
| Code tabs | `::code-group` (requires `comark: true`) | [code-groups](references/upstream/code-groups.md) |
| Monaco editor | `` ```ts {monaco} `` | [editor-monaco](references/upstream/editor-monaco.md) |
| Run code | `` ```ts {monaco-run} `` | [editor-monaco-run](references/upstream/editor-monaco-run.md) |
| Edit files | `<<< ./file.ts {monaco-write}` | [editor-monaco-write](references/upstream/editor-monaco-write.md) |
| Code animations | `` ````md magic-move `` | [code-magic-move](references/upstream/code-magic-move.md) |
| TypeScript types | `` ```ts twoslash `` | [code-twoslash](references/upstream/code-twoslash.md) |
| Import code | `<<< @/snippets/file.js` | [code-import-snippet](references/upstream/code-import-snippet.md) |

### Diagrams & Math

| Feature | Usage | Reference |
|---------|-------|-----------|
| Mermaid diagrams | `` ```mermaid `` | [diagram-mermaid](references/upstream/diagram-mermaid.md) |
| PlantUML diagrams | `` ```plantuml `` | [diagram-plantuml](references/upstream/diagram-plantuml.md) |
| LaTeX math | `$inline$` or `$$block$$` | [diagram-latex](references/upstream/diagram-latex.md) |

### Layout & Styling

| Feature | Usage | Reference |
|---------|-------|-----------|
| Canvas size | `canvasWidth`, `aspectRatio` | [layout-canvas-size](references/upstream/layout-canvas-size.md) |
| Zoom slide | `zoom: 0.8` | [layout-zoom](references/upstream/layout-zoom.md) |
| Scale elements | `<Transform :scale="0.5">` | [layout-transform](references/upstream/layout-transform.md) |
| Layout slots | `::right::`, `::default::` | [layout-slots](references/upstream/layout-slots.md) |
| Scoped CSS | `<style>` in slide | [style-scoped](references/upstream/style-scoped.md) |
| Global layers | `global-top.vue`, `global-bottom.vue` | [layout-global-layers](references/upstream/layout-global-layers.md) |
| Draggable elements | `v-drag`, `<v-drag>` | [layout-draggable](references/upstream/layout-draggable.md) |
| Icons | `<mdi-icon-name />` | [style-icons](references/upstream/style-icons.md) |

### Animation & Interaction

| Feature | Usage | Reference |
|---------|-------|-----------|
| Click animations | `v-click`, `<v-clicks>` | [core-animations](references/upstream/core-animations.md) |
| Rough markers | `v-mark.underline`, `v-mark.circle` | [animation-rough-marker](references/upstream/animation-rough-marker.md) |
| Drawing mode | Press `C` or config `drawings:` | [animation-drawing](references/upstream/animation-drawing.md) |
| Direction styles | `forward:delay-300` | [style-direction](references/upstream/style-direction.md) |
| Note highlighting | `[click]` in notes | [animation-click-marker](references/upstream/animation-click-marker.md) |

### Syntax Extensions

| Feature | Usage | Reference |
|---------|-------|-----------|
| Comark syntax | `comark: true` + `{style="color:red"}` | [syntax-comark](references/upstream/syntax-comark.md) |
| Block frontmatter | `` ```yaml `` instead of `---` | [syntax-block-frontmatter](references/upstream/syntax-block-frontmatter.md) |
| Import slides | `src: ./other.md` | [syntax-importing-slides](references/upstream/syntax-importing-slides.md) |
| Merge frontmatter | Main entry wins | [syntax-frontmatter-merging](references/upstream/syntax-frontmatter-merging.md) |

### Presenter & Recording

| Feature | Usage | Reference |
|---------|-------|-----------|
| Recording | Press `G` for camera | [presenter-recording](references/upstream/presenter-recording.md) |
| Timer | `duration: 30min`, `timer: countdown` | [presenter-timer](references/upstream/presenter-timer.md) |
| Remote control | `slidev --remote` | [presenter-remote](references/upstream/presenter-remote.md) |
| Ruby text | `notesAutoRuby:` | [presenter-notes-ruby](references/upstream/presenter-notes-ruby.md) |

### Export & Build

| Feature | Usage | Reference |
|---------|-------|-----------|
| Export options | `slidev export` | [core-exporting](references/upstream/core-exporting.md) |
| Build & deploy | `slidev build` | [core-hosting](references/upstream/core-hosting.md) |
| Build with PDF | `download: true` | [build-pdf](references/upstream/build-pdf.md) |
| Cache images | Automatic for remote URLs | [build-remote-assets](references/upstream/build-remote-assets.md) |
| OG image | `seoMeta.ogImage` or `og-image.png` | [build-og-image](references/upstream/build-og-image.md) |
| SEO tags | `seoMeta:` | [build-seo-meta](references/upstream/build-seo-meta.md) |

**Export prerequisite**: `pnpm add -D playwright-chromium` is required for PDF/PPTX/PNG export. If export fails with a browser error, install this dependency first.

### Editor & Tools

| Feature | Usage | Reference |
|---------|-------|-----------|
| Side editor | Click edit icon | [editor-side](references/upstream/editor-side.md) |
| VS Code extension | Install `antfu.slidev` | [editor-vscode](references/upstream/editor-vscode.md) |
| Prettier | `prettier-plugin-slidev` | [editor-prettier](references/upstream/editor-prettier.md) |
| Eject theme | `slidev theme eject` | [tool-eject-theme](references/upstream/tool-eject-theme.md) |
| MCP server (AI agents) | `http://localhost:<port>/__mcp` or `slidev mcp` | [tool-mcp](references/upstream/tool-mcp.md) |

### Lifecycle & API

| Feature | Usage | Reference |
|---------|-------|-----------|
| Slide hooks | `onSlideEnter()`, `onSlideLeave()` | [api-slide-hooks](references/upstream/api-slide-hooks.md) |
| Navigation API | `$nav`, `useNav()` | [core-global-context](references/upstream/core-global-context.md) |

## Common Layouts

| Layout | Purpose |
|--------|---------|
| `cover` | Title/cover slide |
| `center` | Centered content |
| `default` | Standard slide |
| `two-cols` | Two columns (use `::right::`) |
| `two-cols-header` | Header + two columns |
| `image` / `image-left` / `image-right` | Image layouts |
| `iframe` / `iframe-left` / `iframe-right` | Embed URLs |
| `quote` | Quotation |
| `section` | Section divider |
| `fact` / `statement` | Data/statement display |
| `intro` / `end` | Intro/end slides |

## Resources

- Documentation: https://sli.dev
- Theme Gallery: https://sli.dev/resources/theme-gallery
- Showcases: https://sli.dev/resources/showcases
