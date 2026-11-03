# Slidev commands

Use `/opt/slidev/node_modules/.bin/slidev build slides.md --out dist --base ./`
through `run_code` in the Docker sandbox. Link the individual entries from
`/opt/slidev/node_modules` into a writable project `node_modules` directory,
as shown in the skill. Use hash routing in headmatter.

The upstream CLI also has commands for development, PDF/PPTX/PNG export,
theme installation, and MCP. Those commands are not exposed by this fork's
workflow and should not be invoked for a browser presentation request.

Full upstream command reference: https://sli.dev/guide/cli
