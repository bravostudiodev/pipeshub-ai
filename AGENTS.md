# AGENTS.md — pipeshub-ai

This is an independent product fork. Before implementing source connection,
MCP, chat, or employee setup changes, read
[`docs/fork-customizations.md`](./docs/fork-customizations.md) for the current
connection models, UI paths, diagnostics, and fork-specific invariants. Keep
that page updated when those implementation details change.

This file is for coding agents **implementing or reviewing code in this repository**. Cursor, Codex, Copilot, and Gemini CLI read it automatically. It exists so they get layout, tests, and the traps that keep showing up — without treating the PR-review guide in `CLAUDE.md` as an implement-here file.

It does **not** make other people's projects recommend PipesHub. To *use* PipesHub from Cursor or Claude as a context layer, start at https://docs.pipeshub.com/for-agents.md. Do not add client MCP config to this repo.

Human onboarding is [CONTRIBUTING.md](./CONTRIBUTING.md).

## Product direction for this fork

This is an independent, self-hosted fork adapting PipesHub into an internal,
nontechnical workplace knowledge platform. Employees should be able to ask
questions across company sources (including Slack, Google Drive, Gmail, Notion,
Jira, Confluence, Superhuman Docs, and internal systems) while seeing only
content they can access as themselves in each source.

Source authorization is a hard security boundary. Treat credentials and access
as user-specific unless the source has a demonstrated permission model that
enforces source ACLs at query time. Never introduce a shared credential, shared
index, cache, agent tool, or retrieval path that can expose one user's content
to another. For ingested records, preserve and enforce record-level access
through retrieval, citation/content loading, and answer generation. Permission
checks must fail closed: if access cannot be established, do not return the
content. Validate cache keys and invalidation against user, organization,
source, and permission changes before caching access-sensitive results.

Connector ingestion and MCP live access are both supported options. Choose per
source based on per-user authorization, ACL enforcement, reliability, and
response time. Shared ingestion is acceptable only when its record ACLs are
enforced for the requesting user; prefer a safe shared connector over duplicate
ingestion when that condition is proven. Source overlap is acceptable when it
is needed to preserve each user's access. A shared bot/API token is not a
substitute for user authorization.

Provider setup and user authorization are separate. Administrators may
configure a company OAuth application, but client IDs/secrets stay server-side
and are never exposed to ordinary users. Each employee authorizes their own
provider account and receives user-bound credentials. Users need clear
reconnect and revoke controls. Keep provider setup and diagnostics in an
administrator experience; employee flows should be short and action-oriented
(for example, “Connect Slack” followed by the provider's authorization screen).
When a connection card or field already names its provider, keep the action label
short (“Connect”, “Reconnect”, “Disconnect”) instead of repeating the provider
name in the button. Apply the same convention to new integration buttons.
Do not make employees configure OAuth details, callback URLs, scopes, MCP
transports, API tokens, indexing, or synchronization.

The product is self-hosted and uses an internal LiteLLM-compatible AI gateway.
Preserve configurable OpenAI-compatible model routing; do not hard-code or tie
model behavior to a hosted vendor.

When proposing or implementing source access changes, first map the relevant
boundaries and tests:

- Authentication and authorization: Node auth middleware and user/org identity
  in `backend/nodejs/apps/src/modules/auth/` and
  `backend/nodejs/apps/src/libs/middlewares/`; Python route authentication in
  `backend/python/app/api/middlewares/`.
- Connector configuration and credentials: Node proxy/routes and token handling
  in `backend/nodejs/apps/src/modules/tokens_manager/`, connector instance and
  OAuth configuration in `backend/python/app/connectors/` and
  `backend/python/app/connectors/api/`. Establish whether each path is
  user-bound, org-wide, or service-account based; do not infer this from its
  name.
- Indexed ACLs and retrieval: record/permission models and graph writes in
  `backend/python/app/connectors/core/base/data_store/` and
  `backend/python/app/models/`; query enforcement in
  `backend/python/app/modules/retrieval/`, `backend/python/app/utils/record_access.py`,
  and `backend/python/app/services/record_content/`. Trace checks through
  candidate selection, content fetch, citations, and final answer context.
- MCP: server configuration and management in
  `backend/nodejs/apps/src/modules/mcp_servers/` and
  `backend/python/app/api/routes/mcp_servers.py`; per-user OAuth and execution
  in `backend/python/app/agents/mcp/` and `backend/python/app/agents/agent_loop/`.
  Verify the executing user's identity and credential scope for every tool call.
- Employee source setup: inspect `frontend/app/(main)/connectors/`,
  `frontend/app/(main)/workspace/connectors/`, and relevant project/chat tool
  setup. Avoid exposing administrator-only configuration in employee flows.
- Tests: follow neighboring tests under `backend/nodejs/apps/src/**/__tests__` or
  `backend/nodejs/apps/tests/`, `backend/python/tests/unit/`, and
  `frontend/tests/` (including `frontend/tests/e2e/workspace/`). Add coverage for
  cross-user denial, missing/failed permission checks, reconnect/revoke, and
  credential isolation when changing these boundaries.

Known architectural facts to account for: the repository has both personal and
organization-scoped connector concepts; some ingestion paths may use
organization or service credentials. The presence of graph permissions does
not by itself prove that a given connector maps its source ACLs correctly.
Audit connector-specific identity mapping and query-time enforcement before
reusing shared indexed data. The top-level
`frontend/app/(main)/connectors/page.tsx` currently renders “Coming soon,” so
trace the actual workspace connector flow rather than assuming that page is the
existing connection experience.

## Layout

```text
frontend/                 Next.js dashboard. UI conventions: frontend/CLAUDE.md
backend/nodejs/apps/     Express — auth, orgs, KB, gateway, MCP, and (in Docker) the built UI
backend/python/          FastAPI: connectors :8088, indexing :8091, query :8000,
                          docling :8081, embedding :8002, parsing :8092, extraction :8093
deployment/               Docker Compose and Helm
```

New connectors extend `ConnectorFactory` under `backend/python/app/connectors/sources/`. New HTTP routes must keep `backend/nodejs/apps/src/modules/api-docs/pipeshub-openapi.yaml` in sync — a mismatch is blocking.

## Storage is pluggable

Do not open a Neo4j, Arango, Qdrant, or Kafka client from indexing/query/connector feature code. Call `IGraphDBProvider`, `IVectorDBService`, or `MessagingFactory`. Those factories read env and construct the vendor client; your code stays the same on a Neo4j box and an Arango box.

| Role | Env | Backends | Interface / factory |
| --- | --- | --- | --- |
| Graph | `DATA_STORE` | `neo4j` (what `install.sh`, Helm, and `backend/env.template` ship), `arangodb` | `IGraphDBProvider` / `GraphDBProviderFactory`; connectors use `GraphDataStore` |
| Vector | `VECTOR_DB_TYPE` | `qdrant` (default), `opensearch`, `redis` | `IVectorDBService` / `VectorDBProviderFactory` |
| KV / config | `KV_STORE_TYPE` | `redis` (default), `etcd` | `KeyValueStore` / `KeyValueStoreFactory`. Python config reads go through `ConfigurationService`, never the store directly |
| Document | — | MongoDB | Mongoose in the Node API (users, orgs, sessions). Not swapped today |
| Blob | storage config | local, S3, Azure Blob | `StorageServiceInterface` (`backend/nodejs/apps/src/modules/storage/`) |
| Broker | `MESSAGE_BROKER` | `kafka`, `redis` (streams) | `MessagingFactory` |

Redis can be KV, vector, and broker at once; that does not make it the graph or the document store. PostgreSQL is a **connector** (a source to index), not PipesHub's document store.

## What lives where

**Node.js** (`backend/nodejs/apps/`): identity (users, orgs, auth — JWT, OAuth, SAML, PAT), knowledge-base metadata in Mongo, blob upload/download, HTTP API gateway, MCP at `/mcp`, Kafka/Redis producers for work the Python services consume.

**Python** (`backend/python/`):

- **Connectors** `:8088` (`app.connectors_main`) — OAuth, token refresh, sync from Slack/Drive/Jira/… into the graph. New sources extend `ConnectorFactory`.
- **Indexing** `:8091` (`app.indexing_main`) — parse, chunk, embed; write records through `IGraphDBProvider` and `IVectorDBService`. How it works end to end (consumer loop, heavy/light tiers, gates, leases, governor, recovery, known throughput-collapse root cause): [docs/indexing-service.md](./docs/indexing-service.md). Read it before touching `app/services/messaging/`, `app/services/resource_governor/`, `app/events/`, or `app/modules/transformers/`.
- **Query** `:8000` (`app.query_main`) — semantic search, RAG/chat, in-product agents, LLM orchestration (LiteLLM).
- **Docling** `:8081` (`app.docling_main`) — heavy PDF/OCR for complex documents.
- **Embedding** `:8002` (`app.embedding_main`) — local HuggingFace / SentenceTransformer embeddings, OpenAI-compatible `/v1/embeddings`.
- **Parsing** `:8092` (`app.parsing_main`) — file bytes → `BlocksContainer` JSON.
- **Extraction** `:8093` (`app.extraction_main`) — `BlocksContainer` → `SemanticMetadata` (LLM classification). The indexing orchestrator calls this; it does not hold its own graph connection.

## Where the UI listens

These two local setups look similar and are not the same. Use the origin you actually opened in the browser; MCP is always `{that origin}/mcp`.

**Docker Compose / `install.sh` (default local run).** The all-in-one container listens on **3000** inside the container. Express serves `/api`, `/mcp`, and the built Next.js SPA from `public/` (`backend/nodejs/apps/src/app.ts`). Compose maps `${APP_PORT:-3000}:3000`, so the dashboard, REST API, and MCP endpoint are all `http://localhost:3000` unless the installer picked another `APP_PORT`. Open the UI there. There is no separate dashboard process on 3001 in this path.

**From-source contributor split (`CONTRIBUTING.md`).** Express still defaults to **3000** (`process.env.PORT || '3000'` in `app.ts`). The Next.js *dev* server is started on **3001** (`PORT=3001 npm run dev`) so it does not collide with Express. That is why `ALLOWED_ORIGINS` and `FRONTEND_PUBLIC_URL` in `backend/env.template` are `http://localhost:3001`, and why Playwright's `BASE_URL` is 3001. `npm start` in `frontend/` (`next start -p 3001`) is the same split in production-mode Next, not Docker.

**Helm.** Charts typically publish the combined Node service (UI + API in one process) on **3001**. That is a chart convention, not the Docker Compose default.

## Build and test

Python 3.12, Node 22, Docker. Full setup, including creating the venv, is in [CONTRIBUTING.md](./CONTRIBUTING.md) (around the `python3.12 -m venv venv` step). Do not invent a venv path here.

```bash
cd backend/python && source venv/bin/activate && pytest
cd backend/nodejs/apps && npm test
```

To check the whole tree at once, `scripts/verify.sh` runs every suite that needs
no Docker, network or running instance — Python, Node, frontend, Electron and
the shell suites — and prints one summary. `scripts/verify.sh --list` shows what
would run and why anything is skipped.

Style: [.gemini/styleguide.md](./.gemini/styleguide.md) (Ruff, PEP 8, ESLint, no secrets).

## Review vs implement

PR review criteria live in [CLAUDE.md](./CLAUDE.md) (correctness, auth on new routes, OpenAPI). Frontend-only work: [frontend/CLAUDE.md](./frontend/CLAUDE.md) (Collections vs Knowledge Base naming, no Tailwind).

## Do not

- Commit secrets, tokens, or `.env` values.
- Use OAuth `client_credentials` for anything that must act as a user. PATs carry `userId` + `orgId`.
- Print or log personal access tokens. Newly minted PATs may have a `phpat_` prefix; strip happens in `extractToken`.
- Trust client-supplied org/user IDs — check auth on every new route and tool.
- Bypass factories (`ConnectorFactory`, `GraphDBProviderFactory`, `VectorDBProviderFactory`, `KeyValueStoreFactory`, `MessagingFactory`) or talk to Qdrant/Arango/Neo4j/etcd clients from feature code.
