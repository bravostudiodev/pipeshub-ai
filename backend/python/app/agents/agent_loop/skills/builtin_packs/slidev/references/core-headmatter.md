# Slidev headmatter

Headmatter is the first YAML block at the top of `slides.md`. Common fields
include `title`, `theme`, `layout`, `fonts`, `aspectRatio`, `routerMode`,
`remoteAssets`, and `download`.

This renderer enforces these values for offline ZIP portability:

```yaml
theme: default # or seriph
base: ./
routerMode: hash
remoteAssets: false
fonts:
  provider: none
download: false
```

Only the preinstalled `default` and `seriph` themes are supported. Do not
reference remote themes, fonts, images, or other assets. Include assets in the
tool input and use relative paths. The renderer replaces conflicting values
for enforced fields and rejects unsupported themes.

Full upstream guide: https://sli.dev/custom/#headmatter
