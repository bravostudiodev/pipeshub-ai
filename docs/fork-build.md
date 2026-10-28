# OddJeeves build pipeline

The fork uses two prebuilt images to keep the normal application image build
from reinstalling Python packages and operating system dependencies on every
commit. Their contents are defined by [`Dockerfile.base`](../Dockerfile.base):

| Image tag | Docker target | Contents | Rebuild when |
| --- | --- | --- | --- |
| `pipeshubai-base:python-deps` | `python-deps` | Python dependencies from `backend/python/pyproject.toml`, CPU PyTorch, Crawl4AI, Chromium, and bundled language/model assets | Python dependencies, browser setup, or bundled model choices change |
| `pipeshubai-base:runtime` | `runtime-base` | Runtime OS libraries, Node.js 20, LibreOffice, fonts, and Cypher Shell | Runtime packages, Node major version, or document conversion requirements change |

The application [`Dockerfile`](../Dockerfile) currently defaults to these full
image references:

```text
doc.lan.dc11.us/platform/pipeshubai-base:python-deps
doc.lan.dc11.us/platform/pipeshubai-base:runtime
```

Earlier fork build instructions used `doc.oddbytes.com/platform/pipeshubai-base`
for the same two tags. Check which registry name resolves in the build
environment before publishing or changing the Dockerfile defaults. These are
two distinct image references unless the registry is explicitly configured to
serve both names. `PYTHON_DEPS_IMAGE` and `RUNTIME_BASE_IMAGE` are Docker build
arguments that override the defaults for a build; the Bravo image build stage
does not currently pass overrides.

To rebuild and push the base images to the registry named in the current
Dockerfile, from the repository root:

```bash
docker build -f Dockerfile.base --target python-deps --build-arg PYTHON_DEPS_BASE=build-base --build-arg BUNDLE_BGE_EMBEDDING=0 -t doc.lan.dc11.us/platform/pipeshubai-base:python-deps .
docker push doc.lan.dc11.us/platform/pipeshubai-base:python-deps
docker build -f Dockerfile.base --target runtime-base -t doc.lan.dc11.us/platform/pipeshubai-base:runtime .
docker push doc.lan.dc11.us/platform/pipeshubai-base:runtime
```

Publish a new base before starting an application image build that depends on
it. A normal application code change should only rebuild the application
image. The default Python base omits the large local BGE dense embedding model;
see `BUNDLE_BGE_EMBEDDING` in `Dockerfile.base` when local embedding is needed.

## MCP SDK dependency checkpoint

The MCP runtime now requires `mcp==2.3.0` and `httpx2==2.12.0` rather than
FastMCP. Rebuild/publish `python-deps` from the changed manifest before building
the application image. Rebuilding only application code against the old base
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
`backend/nodejs/apps`, then prunes Node development dependencies. It runs
`npm ci` and `ELECTRON_STATIC=1 npm run build` in `frontend` concurrently with
the backend build, and waits for both before the image stage. Either failure
fails the stage. These are two different package directories and lockfiles;
the frontend's legacy peer-dependency setting applies only to its install, so
parallel installs do not change each other's npm configuration. The `~/.npm` cache avoids repeated
package downloads, but `npm ci` still recreates each directory's
`node_modules`. `frontend/.next/cache` also persists Next.js build cache; it is
excluded from the Docker context and is not part of the shipped static export.
Cache restore/save overhead can be substantial, so compare warm build times on
Bravo before assuming a speedup. The stage leaves `backend/nodejs/apps/dist`, its production
`node_modules`, and `frontend/out` in the build workspace.

The **Image build** stage builds the root Dockerfile from that workspace. It
pulls the two prebuilt base images, copies Python packages and model/browser
assets from `python-deps`, and copies the already built Node and frontend
artifacts. It does not run `npm ci`, `npm run build`, or a fresh Python
dependency resolution. The image stage still spends time transferring and
copying large assets; the base images mainly avoid repeating dependency and
OS package installation. If the base images are rebuilt, update their tags or
deployment process so the image build consumes the intended versions.

The upstream Docker Compose examples in `deployment/docker-compose/` default
to public `pipeshubai/pipeshub-ai-base` images and can override them using
`PYTHON_DEPS_IMAGE` and `RUNTIME_BASE_IMAGE`. Those Compose defaults do not
describe the private Bravo build.
