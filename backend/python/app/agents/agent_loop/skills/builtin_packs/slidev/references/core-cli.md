# Slidev commands

The supported renderer command is the fixed `npm run build` in the dedicated
prebuilt image. It creates a static SPA under `dist/` with the relative base
and hash navigation required for local serving.

The upstream CLI also has commands for development, PDF/PPTX/PNG export,
theme installation, and MCP. Those commands are not exposed by this fork's
tool and must not be invoked through another sandbox or shell tool for a
presentation request.

Full upstream command reference: https://sli.dev/guide/cli
