# Slidev Markdown syntax

Slidev uses Markdown with Vue and code-block enhancements. A line containing
three hyphens separates slides. The first frontmatter block configures the
deck; later frontmatter blocks configure individual slides. HTML comments
inside a slide are presenter notes.

```md
---
theme: default
title: Example
---
# First slide

---
layout: two-cols
# Second slide
::right::
Right column
```

Use fenced code blocks for syntax highlighting. Add `{2,3}` after a language
to highlight lines, or `{1|2-3|all}` for click-based highlighting. `v-click`
and `v-clicks` reveal content incrementally. Use `<<< ./file.ts` to include a
local file after adding it as a renderer supporting file.

Full upstream guide: https://sli.dev/guide/syntax
