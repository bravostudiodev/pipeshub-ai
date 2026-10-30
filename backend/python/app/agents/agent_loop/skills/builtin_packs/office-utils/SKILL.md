---
name: office-utils
description: "Low-level support skill for hand-editing raw XML inside an existing .docx or .pptx file. Use only for reading or making a small targeted edit to an existing Office document; never use it to create a new presentation. For new browser-based presentations, use the slidev skill."
metadata:
  agent-loop:
    version: 1.0.0
    category: documents
    subcategory: office-xml
    tags: [docx, pptx, xml, openxml, office-utils]
    status: active
    source: builtin
    pack_name: office-utils
    pack_version: 1.0.3
---

# Office Open XML utilities

## Overview

A `.docx` or `.pptx` file is a ZIP archive containing a tree of XML parts (`word/document.xml`, `ppt/slides/slide1.xml`, relationship files, content-type manifests, ...). Editing it directly means: unpack the ZIP, edit the XML text, repack the ZIP. No LibreOffice or other converter is required for this — it is pure `zipfile` + text editing.

For new presentations, use the `slidev` skill and its offline renderer. This skill is for targeted edits to existing `.docx` or `.pptx` files; it does not create presentations. The `docx`, `xlsx`, and `pdf` skills continue to cover their respective document workflows.

## Quick Reference

| Task | Command |
|------|---------|
| Unpack a file to a directory tree | `python skills/office-utils/scripts/unpack.py <file.docx\|pptx> <out_dir/>` |
| Repack a directory tree back to a file | `python skills/office-utils/scripts/pack.py <out_dir/> <file.docx\|pptx>` |

## Workflow

1. **Unpack**: `python skills/office-utils/scripts/unpack.py presentation.pptx unpacked/`. This extracts every part into `unpacked/`, pretty-printing every `.xml` file (one element per line) so edits are readable and diffable. A `_unpack_manifest.json` file records the original entry order and compression — `pack.py` reads it back so re-zipping doesn't accidentally change part ordering, which some Office readers are picky about.
2. **Edit**: make targeted edits to the relevant XML file(s) under `unpacked/` (e.g. `unpacked/word/document.xml`, `unpacked/ppt/slides/slide1.xml`). Prefer the smallest possible edit — a single attribute or run of text — over rewriting a whole XML subtree, so you're less likely to break sibling elements you didn't intend to touch.
3. **Repack**: `python skills/office-utils/scripts/pack.py unpacked/ output.pptx`. This re-zips using the manifest's original entry order, and validates that every `.xml` part is still well-formed (parses cleanly) before writing the final file — if any part is malformed, it fails loudly with the offending file name and line instead of silently producing a corrupt document.

## Common pitfalls

- **Don't reorder ZIP entries.** Some parsers (notably older Office/PowerPoint) are sensitive to `[Content_Types].xml` and `_rels/.rels` being near the start of the archive. `pack.py`'s manifest-driven ordering exists specifically to avoid this — don't hand-roll your own zipping.
- **Keep relationship IDs (`r:id`) consistent.** If you add a new part (e.g. an image), you must add both a `<Relationship>` entry in the owning part's `_rels/*.rels` file AND a reference to that same ID from the XML that uses it. Adding one without the other produces a file that "opens" but shows a broken-image icon or corruption warning.
- **Escape XML special characters** (`&`, `<`, `>`) in any text you insert into a `<w:t>`/`<a:t>` run — a raw ampersand will make the part invalid XML and fail the pack-time validation.
- **This skill has no way to render a preview.** Visual verification (rendering the file to an image) requires LibreOffice, which is not available in this environment yet — verify structurally (does it still parse? do the relationship IDs still resolve?) rather than visually.

## Dependencies

Pure Python standard library (`zipfile`, `xml.dom.minidom`, `json`) — no packages to install.
