# OddJeeves build pipeline

The application [`Dockerfile`](../Dockerfile) builds `FROM` one prebuilt
image, `pipeshubai-base:app`, so a normal commit only builds, pushes, and scans
its application-code layers. That image is assembled from two intermediate
images. All three are defined by [`Dockerfile.base`](../Dockerfile.base):

| Image tag | Docker target | Contents | Rebuild when |
| --- | --- | --- | --- |
| `pipeshubai-base:python-deps` | `python-deps` | Python dependencies from `backend/python/pyproject.toml`, CPU PyTorch, Crawl4AI, Chromium, and bundled language/model assets | Python dependencies, browser setup, or bundled model choices change |
| `pipeshubai-base:runtime` | `runtime-base` | Runtime OS libraries, Node.js 20, LibreOffice, fonts, and Cypher Shell | Runtime packages, Node major version, or document conversion requirements change |
| `pipeshubai-base:app` | `app-base` | `runtime` plus everything from `python-deps`, the runtime user, and runtime environment | Either of the two above is rebuilt |

The application Dockerfile defaults to
`doc.lan.dc11.us/platform/pipeshubai-base:app` (override with the
`APP_BASE_IMAGE` build argument). Earlier fork build instructions used
`doc.oddbytes.com/platform/pipeshubai-base`; check which registry name resolves
in the build environment before publishing or changing the default.

To rebuild and push the base images, from the repository root:

```bash
docker build -f Dockerfile.base --target python-deps --build-arg PYTHON_DEPS_BASE=build-base --build-arg BUNDLE_BGE_EMBEDDING=0 -t doc.lan.dc11.us/platform/pipeshubai-base:python-deps .
docker push doc.lan.dc11.us/platform/pipeshubai-base:python-deps
docker build -f Dockerfile.base --target runtime-base -t doc.lan.dc11.us/platform/pipeshubai-base:runtime .
docker push doc.lan.dc11.us/platform/pipeshubai-base:runtime
```

Then assemble `app` from the published images without rebuilding them:

```bash
docker build -f Dockerfile.base --target app-base \
  --build-arg PYTHON_DEPS_SOURCE=doc.lan.dc11.us/platform/pipeshubai-base:python-deps \
  --build-arg RUNTIME_BASE_SOURCE=doc.lan.dc11.us/platform/pipeshubai-base:runtime \
  -t doc.lan.dc11.us/platform/pipeshubai-base:app .
docker push doc.lan.dc11.us/platform/pipeshubai-base:app
```

Publish a new `app` base before starting an application image build that
depends on it. A normal application code change should only rebuild the
application image. The default Python base omits the large local BGE dense
embedding model; see `BUNDLE_BGE_EMBEDDING` in `Dockerfile.base` when local
embedding is needed.

## MCP SDK dependency checkpoint

The MCP runtime now requires `mcp==2.3.0` and `httpx2==2.12.0` rather than
FastMCP. Rebuild/publish `python-deps`, then `app`, from the changed manifest before
building the application image. Rebuilding only application code against the old base
will not install these packages. The runtime OS base does not need a rebuild
for this dependency change. Ensure the application build pulls the newly
published dependency image rather than reusing a cached older tag.

Verify the dependency image, then verify the same versions in the resulting
application image:

```bash
docker run --rm --entrypoint python doc.lan.dc11.us/platform/pipeshubai-base:python-deps -c 'from importlib.metadata import version; from mcp import Client; import httpx2; assert version("mcp") == "2.3.0"; assert version("httpx2") == "2.12.0"; print("MCP SDK dependencies verified")'
```

Local SDK/HTTP/SSE/STDIO regressions have been exercised with those versions;
base-image builds and real-provider/proxy smoke checks have not yet been run.
Normal deployment remains the intended path after those checks; no separate
canary or traffic-splitting process is required.

## Bravo stages

[`../.bravo/config.yaml`](../.bravo/config.yaml) runs **App build** with
`platform/node:20`. It runs `npm ci` and `npm run build` in
`backend/nodejs/apps`, then prunes Node development dependencies. It then runs
`npm ci` and `ELECTRON_STATIC=1 npm run build` in `frontend`. The builds run
sequentially to reduce potential peak resource demand after an unexplained
concurrent-build failure; phase markers help identify where termination occurred.
Either failure fails the stage. These are different package directories and
lockfiles; the frontend's legacy peer-dependency setting applies only to its
install. The `~/.npm` cache avoids repeated
package downloads, but `npm ci` still recreates each directory's
`node_modules`. `frontend/.next/cache` also persists Next.js build cache; it is
excluded from the Docker context and is not part of the shipped static export.
Cache restore/save overhead can be substantial, so compare warm build times on
Bravo before assuming a speedup. The stage leaves `backend/nodejs/apps/dist`, its production
`node_modules`, and `frontend/out` in the build workspace.

The **Image build** stage builds the root Dockerfile from that workspace on top
of `pipeshubai-base:app`, copying only the built Node and frontend artifacts
and the Python application code (about 800 MB, most of it Node
`node_modules`). The base layers already exist in the registry and are not
pushed again. If the base images are rebuilt, update their tags or deployment
process so the image build consumes the intended versions.

The upstream Docker Compose examples in `deployment/docker-compose/` default
to public `pipeshubai/pipeshub-ai-base` images and can override them using
`PYTHON_DEPS_IMAGE` and `RUNTIME_BASE_IMAGE`. The fork's Dockerfile no longer
reads those arguments, so Compose builds from source use the `APP_BASE_IMAGE`
default unless it is passed explicitly.

## Sandbox image

The code execution sandbox is built separately from the application image
using [`deployment/sandbox/Dockerfile`](../deployment/sandbox/Dockerfile). The
updated sandbox image should be published under a new reference, for example:

```text
doc.oddbytes.com/platform/pipeshubai-sandbox:0.9.1.oddyssey1-2
```

The sandbox Dockerfile includes Python's `python-pptx`, Node's `pptxgenjs`,
and pinned Slidev dependencies in `/opt/slidev`, and runs as the non-root
`sandbox` user. Node 22 is required by Slidev. The built-in Slidev skill uses
`run_code` and the existing artifact delivery path; it does not use a separate
renderer image or tool. Decks are built only through
`/opt/slidev/build_deck.py` (source in `deployment/sandbox/slidev/`), which
disables code splitting and embeds all JS, CSS, fonts, and images into one
`dist/index.html`. It then opens every slide in headless Chromium (installed in
the image) with all clicks revealed and fails the build when text leaves the
slide, is clipped, or overlaps other text, so the agent fixes the layout before
delivering. Changing that helper, its Vite config, or `layout_check.js` requires rebuilding
and publishing the sandbox image. The image also installs the Inter font family and
provides OddBytes logos, icons, and stickers under `/opt/brand-assets/oddbytes/`
for explicitly branded work. Logos and icons are available as self-contained SVGs
and ready-to-use transparent PNGs; `README.md` in that directory lists the variants.
Changes to those assets require rebuilding and publishing the sandbox image.
The Youngest accent font is not included. Browser
presentations must include any chosen fonts and icons in their delivered ZIP.
Only the Docker sandbox image includes these assets and Slidev by default. The Slidev skill and vendored references are adapted from the
MIT-licensed upstream Slidev skill at commit
`a42aff28dd75f26eb5abbf3d616ea022c3d08924`; its license is in the skill pack.

Rebuild and publish both the application and sandbox images before switching
deployments to this workflow. The external wrapper chart must point to the new
sandbox image and remove its separate Slidev image pull and smoke test. The
previous sandbox image does not contain Slidev.

Package requests still use separate networked installer containers. Python
packages use `SANDBOX_PIP_INDEX_URL` (default `https://pypi.org/simple`), and
TypeScript packages use `SANDBOX_NPM_REGISTRY` (default
`https://registry.npmjs.org`). Generated code runs in another container with
networking disabled when code network access is off. The Helm deployment must
control and permit the installer containers' registry route independently of
generated-code networking.

To build and publish it manually from the repository root:

```bash
docker build -f deployment/sandbox/Dockerfile -t doc.oddbytes.com/platform/pipeshubai-sandbox:0.9.1.oddyssey1-2 deployment/sandbox
docker push doc.oddbytes.com/platform/pipeshubai-sandbox:0.9.1.oddyssey1-2
```

After the image is available locally, verify the prebaked document libraries
and generate/read a PowerPoint file without network access or running as root:

```bash
docker run --rm --network none --user sandbox --entrypoint sh doc.oddbytes.com/platform/pipeshubai-sandbox:0.9.1.oddyssey1-2 -ec '
python -c "import pptx; print(\"python-pptx:\", pptx.__version__)"
node -e '\''(async () => { const pptxgen = require("/home/sandbox/node_modules/pptxgenjs"); const pptx = new pptxgen(); pptx.addSlide().addText("Sandbox smoke test"); await pptx.writeFile({ fileName: "/tmp/sandbox-smoke.pptx" }); })().catch((err) => { console.error(err); process.exit(1); });'\''
python -c "from pptx import Presentation; p = Presentation(\"/tmp/sandbox-smoke.pptx\"); assert len(p.slides) == 1; print(\"PowerPoint smoke test passed\")"
'
```

This image smoke test verifies the libraries baked into the image, but does
not verify Kubernetes runtime isolation or the package installer and its
network route. Before enabling execution, verify that Docker reports
`name=rootless` in its `SecurityOptions`. The Helm executor pod uses
`hostUsers: true` and UID/GID/fsGroup 1000 for sandbox containers; the outer
executor container remains `privileged: true` to initialize and run the
rootless Docker daemon. Rootless mode applies to the Docker engine and does not
remove the outer container's privileged setting. Also verify per-run CPU and
memory limits in practice: startup reports the daemon's cgroup driver and
version, but does not guarantee enforcement. Per-run limits may be ignored
unless the daemon uses the systemd cgroup driver with cgroup v2. Kubernetes
CPU and memory limits on the outer pod remain configured.
