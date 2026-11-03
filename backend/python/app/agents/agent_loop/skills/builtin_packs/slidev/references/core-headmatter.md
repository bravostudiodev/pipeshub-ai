# Slidev headmatter

Headmatter is the first YAML block at the top of `slides.md`. Common fields
include `title`, `theme`, `layout`, `fonts`, `aspectRatio`, `routerMode`,
`remoteAssets`, and `download`.

Set these values for offline ZIP portability:

```yaml
theme: default # or seriph
base: ./
routerMode: hash
remoteAssets: false
fonts:
  provider: none
download: false
favicon: ""
```

Only the preinstalled `default` and `seriph` themes are supported. Do not
reference remote themes, fonts, images, or other assets. Include assets in the
project and use relative paths. The coding sandbox does not automatically
replace conflicting values, so check the deck headmatter before building.

Full upstream guide: https://sli.dev/custom/#headmatter
