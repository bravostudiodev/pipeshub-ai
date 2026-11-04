# Slidev commands

Build decks only with `python3 /opt/slidev/build_deck.py <project> <output.zip>`
through `run_code` in the Docker sandbox, as shown in the skill. It runs
`slidev build` with the preinstalled packages and embeds everything into a
self-contained `dist/index.html`. Do not run `slidev build` directly. Use hash
routing in headmatter.

The upstream CLI also has commands for development, PDF/PPTX/PNG export,
theme installation, and MCP. Those commands are not exposed by this fork's
workflow and should not be invoked for a browser presentation request.

Full upstream command reference: https://sli.dev/guide/cli
