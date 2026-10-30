# Slidev renderer image

The `.bravo/config.yaml` Slidev image stages build this context as
`doc.oddbytes.com/platform/pipeshubai-slidev:1.0.0-1`; the non-main stage
builds without pushing, and the main-branch stage publishes it.

The base image is `docker.io/tangramor/slidev:latest`, resolved on 2026-10-29
to `sha256:79c835dbc489be324f697a975842cd222371e62e62a388e200cf092ca0925db9`.
The digest is pinned in the Dockerfile. The image installs only the exact
dependencies in `package-lock.json`; it does not run the upstream image's
`npm install` / development-server entrypoint. It runs as UID/GID 1000, with
its project directory owned by that user. Slidev and both supported themes
are present before a render begins; the application uses Python's standard
library to validate and package the resulting files.

The application creates a fresh container with networking disabled, stages
inputs using the Docker archive API, and runs the fixed production build.
The container never receives npm arguments or a model-supplied manifest. The
application reads the static output and returns one ZIP containing the site,
editable source, included assets, and a local serving README. It does not
provide a hosted preview.

The application code that invokes this image is part of the main PipesHub
application image. Build and publish the updated application as
`doc.oddbytes.com/platform/pipeshubai:0.9.1.oddyssey2`; the existing
`0.9.1.oddyssey1` image does not contain the renderer. The app image stages in
`.bravo/config.yaml` remain commented and must be enabled only through the
existing application release process. Enable `SLIDEV_ENABLED=true` only after
that application image and this renderer image are available to the deployment.
The Helm values expose `config.slidevEnabled` (default `false`) and
`config.slidevDockerImage` (default
`doc.oddbytes.com/platform/pipeshubai-slidev:1.0.0-1`); the tool also requires
the existing code-execution gate and `SANDBOX_MODE=docker`.

Run this smoke test after building the image. It builds a two-slide deck and a
local SVG asset for each supported theme with networking disabled, then checks
the static site exists:

```sh
docker build -t doc.oddbytes.com/platform/pipeshubai-slidev:1.0.0-1 deployment/slidev
docker run --rm --network none --memory 1g --cpus 1 --pids-limit 128 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --user 1000:1000 --entrypoint sh \
  doc.oddbytes.com/platform/pipeshubai-slidev:1.0.0-1 -ec '
mkdir -p public
printf "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"16\" height=\"16\"><circle cx=\"8\" cy=\"8\" r=\"7\" fill=\"#276EF1\"/></svg>" > public/smoke.svg
for theme in default seriph; do
cat > slides.md <<EOF
---
theme: ${theme}
title: Offline Slidev smoke test
base: ./
routerMode: hash
remoteAssets: false
fonts:
  provider: none
download: false
favicon: ""
---
# Offline build

![Local asset](/smoke.svg)

---
# Hash routing

Two slides, one local asset, no network.
EOF
npm run build
test -s dist/index.html
if grep -q 'cdn.jsdelivr.net' dist/index.html; then
  echo "Unexpected CDN reference in static output" >&2
  exit 1
fi
test -d dist/assets
rm -rf dist
done
'
```

The resulting `dist/` directory can be served locally with
`python3 -m http.server 8000 --directory dist`; hash routing works without
server-side rewrites.

## Upstream skill attribution

The built-in `slidev` skill is adapted from
[`slidevjs/slidev/skills/slidev`](https://github.com/slidevjs/slidev/tree/a42aff28dd75f26eb5abbf3d616ea022c3d08924/skills/slidev)
at commit `a42aff28dd75f26eb5abbf3d616ea022c3d08924` (2026-10-23). It is
distributed under the upstream MIT license; see `builtin_packs/slidev/LICENSE`.
