# Internal knowledge platform fork

This repository is an independent PipesHub fork branded **OddJeeves** and adapted into a self-hosted,
internal knowledge platform for nontechnical employees. The upstream services
and connector catalog remain in place; the changes below add a simpler source
connection experience and protect each employee's source identity.

## Product and authorization model

Employees use `/chat` to ask questions across company knowledge sources. The
connection strip stays visible during new chats and existing conversations. It
uses compact provider cards, short action labels (`Connect`, `Reconnect`, and
`Disconnect`), and horizontal scrolling when the available width is too small.
Company-wide provider setup belongs to workspace administrators. The user card
only reports and changes the current user's connection.

For OAuth MCP sources, the organization configures one MCP instance and OAuth
application. Every employee authorizes their own account, and MCP tool calls
must resolve credentials for the authenticated caller. Organization server
configuration is not a user credential. Never use an admin token, shared bot
token, or another user's credential as a fallback. A connected status is based
on saved user credentials; tool discovery is a separate diagnostic action and
must not be required to complete authorization.

The current chat cards cover:

| Card | Connection model | Configuration and implementation |
| --- | --- | --- |
| Slack | Live official Slack MCP over Streamable HTTP and per-user OAuth | Uses the organization's designated `https://mcp.slack.com/mcp` instance. It does not use Slack message ingestion or a shared bot token for this flow. |
| Notion | Live MCP and per-user OAuth | Reuses the organization-configured Notion MCP instance. |
| Miro | Live custom MCP and per-user OAuth | Reuses the organization-configured Miro instance and its OAuth flow. |
| Jira | Live Atlassian Rovo MCP and per-user OAuth | Uses the designated Atlassian Rovo instance. The card is labeled Jira for employees. |
| Gmail | Live Google MCP and per-user OAuth | Uses the organization-configured Gmail MCP instance. |
| Google Drive | Live Google MCP and per-user OAuth | Uses the organization-configured Drive MCP instance. |
| Google Calendar | Live Google MCP and per-user OAuth | Uses the organization-configured Calendar MCP instance with Google's documented read-only OAuth scopes. The service is currently in Google's Developer Preview. |
| Superhuman Docs | Live MCP with a personal, read-only API token | Organization config provides the endpoint. Each employee supplies their own token in chat; `/superhuman-guide/` explains how to create it and links to the exact provider settings page. |

The MCP cards are implemented in
`frontend/app/(main)/chat/components/slack-connection-card.tsx` (the filename
is historical). Connection status and authorization use the existing MCP
server APIs in `frontend/app/(main)/workspace/mcp-servers/api.ts` and
`backend/python/app/api/routes/mcp_servers.py`. Designation is based on provider
metadata and validated endpoint/auth characteristics, not a database ID.
Custom MCP instances may be identified by explicit type/name metadata together
with transport and auth mode. Keep these matchers strict enough to avoid
accidentally selecting a different server.

The Superhuman Docs employee guide is under
`frontend/app/(main)/superhuman-guide/`, with screenshots in
`frontend/public/guides/superhuman-docs/`. The app is statically exported in
production, so guide images should be referenced as static public assets and
should not depend on Next's image optimization server.

For the administrator steps to configure Google Calendar or add another
provider connection, see [MCP connection setup](mcp-connection-setup.md).

The existing **Confluence Data Center Personal** connector remains available
through connector administration, with organization-managed URL, sync filters,
and cadence and user-specific credentials. It is not currently shown as a
connection card in `/chat`.

## MCP retrieval diagnostics

MCP retrieval tracing is feature-flagged by
`ENABLE_MCP_RETRIEVAL_TRACE` and is disabled by default. Its implementation is
in `backend/python/app/agents/mcp/retrieval_trace.py`, with instrumentation in
the agent loop and MCP service paths. It records user/run/organization/instance
correlation, credential ownership and presence, tool discovery and schema
fingerprints, invocation metadata, safely filtered arguments, outcomes, timing,
result counts, returned IDs, timestamp bounds, and pagination/truncation
metadata.

Trace data deliberately excludes message bodies, free-text search terms,
access/refresh tokens, client secrets, authorization headers, private URLs, and
raw tool responses. It is stored in the existing configuration/KV layer with
a seven-day TTL and a compact per-organization index; list and compare requests
do not scan all organization keys. The existing comparison limit is ten runs.
The admin view is at `/workspace/mcp-servers/diagnostics/` under workspace MCP
administration. Its API requires an administrator and scopes results to that
administrator's organization. Do not expose trace records to ordinary
employees or use trace metadata as a substitute for source authorization.

Tracing should remain off outside diagnosis unless an operator explicitly
enables the feature flag. Add only metadata needed to compare retrieval
behavior, and keep redaction tests for new argument shapes.

## Additional implementation notes

On the login screen, Google is the initially selected tab when the organization
offers Google among multiple sign-in methods. Otherwise, the first available
method remains the default; users can still switch tabs.

The workspace sidebar shows the **People** section (Users and Teams) only to
administrators. This is navigation visibility, not an API authorization rule.

The main chat sidebar also shows **Collections**, **All Records**, **All
Artifacts**, and **My agents** only to administrators. Regular members keep
New Chat, Search Chats, Inbox, and their conversation history. This hides
navigation and does not change route or API permissions.

The fork's Bravo stages and two private prebuilt images are documented in
[`fork-build.md`](fork-build.md).

- Keep MCP transport/client behavior provider-neutral. Do not add Slack-specific
  prompt instructions or phrase-based tool selection to address stale answers.
- OAuth callbacks, token refresh, and tool invocation should use existing MCP
  authorization paths. A reconnect must authorize the same current user again;
  disconnect removes that user's credential only.
- Connection status APIs for employees return configuration availability and
  the caller's own saved state. Never serialize OAuth client secrets or raw
  credential payloads to the browser.
- Provider connection failures should be visible and actionable in the card;
  preserve useful safe server diagnostics and request correlation IDs rather
  than silently swallowing errors.
- Continue routing model requests through the self-hosted,
  OpenAI-compatible/LiteLLM gateway. Do not make these integrations depend on a
  hosted model vendor.

OAuth popup handling accepts completion messages only from the popup opened by
that card and opens the window synchronously from the click action before
loading the authorization URL. This prevents one successful provider flow from
being mistaken for success or failure by every other card listening on the
page, and avoids browser popup blockers.

Provider-hosted OAuth pages can fail without redirecting back to the app. While
an OAuth MCP authorization is pending, every chat connection card offers
**Start over**. This closes the current popup and requests a new authorization
URL and state for the same signed-in user. Closing a provider popup without a
successful callback is treated as a failed attempt. The card then shows
**Try again** and a short error inside the card. If a previous connection
exists, its **Connected** status remains visible alongside **Try again**;
the failed attempt does not remove its credentials. A provider error page that
stays open cannot be inspected by the app, so **Start over** remains available
until the popup closes, returns an error callback, or times out. Reauthorizing
an MCP instance from chat, workspace MCP pages,
or an agent credential dialog preserves the current credential until the new
callback succeeds. In these UI flows, only an explicit Disconnect removes the
existing credential.

Slack connector ingestion also has fork-specific recovery diagnostics. Sync
logs include channel, checkpoint age, effective time window, pagination, and
safe provider error/status information. A partial history walk must not advance
the sync checkpoint, because doing so can hide messages after a failed page.
Slack history/thread utilities log request context without dumping message
bodies. These changes apply to the ingestion connectors; they do not turn the
Slack chat card into an ingestion flow.

## Main extension points

- Employee cards and guide: `frontend/app/(main)/chat/` and
  `frontend/app/(main)/superhuman-guide/`.
- MCP administration and diagnostics: `frontend/app/(main)/workspace/mcp-servers/`.
- MCP provider discovery, user auth status, callback, and trace API:
  `backend/python/app/api/routes/mcp_servers.py`.
- MCP credential resolution and tool execution:
  `backend/python/app/agents/mcp/` and
  `backend/python/app/agents/agent_loop/`.
- Confluence personal connector: `backend/python/app/connectors/sources/atlassian/confluence_datacenter_personal/`.
- User-facing connection, trace, credential isolation, and authorization tests:
  `frontend/app/(main)/chat/components/__tests__/`,
  `frontend/app/(main)/workspace/mcp-servers/diagnostics/__tests__/`,
  `backend/python/tests/unit/agents/mcp/`, and
  `backend/python/tests/unit/api/routes/`.

When changing these boundaries, inspect the current call path and tests first.
The integration names and configuration mechanisms can evolve; the invariant
is per-user source authorization and organization-scoped administration.

## Outbound HTTP proxy and request logging

Workspace administrators can turn off **Public web search and URL fetching** in
Workspace → Labs. The `ENABLE_PUBLIC_WEB_ACCESS` platform flag applies to all
users and agents. When off, the backend omits web search and Fetch URL from new
agent runs and refuses calls from already-created tools. It also blocks public
URL downloads used by remote images and Skills imports; uploaded Skills and
in-cluster service requests continue to work. The setting is read live from
platform settings, so turning it off does not require a restart. If the settings
store cannot be read, public web access is denied. MCP tool calls, OAuth, and
model requests are separate paths and are not controlled by this switch.
If a public web request receives an outbound proxy or network-policy denial,
the agent stops public web requests for that turn and tells the user it could
not complete the search or fetch. It does not keep broadening the search or
trying other public URLs.

Python services read one setting, `OUTBOUND_PROXY_URL` (`backend/env.template`), and
route public HTTP(S) through it; `OUTBOUND_PROXY_BYPASS` names exact internal hostnames that stay
direct. Loopback, private IPs, Kubernetes service names and `*.svc` / `*.cluster.local` stay
direct. Service endpoint variables do not add bypasses. `app/utils/outbound_proxy.py`
(`select_route`) is the routing decision.
`app/utils/outbound_http.py` is installed first in every service (`outbound_bootstrap`), exports
the standard proxy variables, and instruments httpx, aiohttp, requests, curl_cffi and urllib.
Each instrumented request logs one
`outbound_http {json}` line: destination host and port, method, `via` (`proxy`/`direct`), route
reason, an optional request label, outcome and
the trace request id. Paths, queries, headers, cookies and bodies are never logged. SSRF refusals log
`outcome=denied`; a client that connects directly to a destination the policy proxies logs
`route_reason=proxy_not_applied` at warning level.

URL fetching keeps its DNS-pinning guarantees: each hop is resolved and checked locally, and the
proxy is handed the validated IP, never the hostname. Proxied untrusted fetches therefore use only
the `requests` strategy (curl cannot bind a proxied destination) and need working local DNS.
A proxy that refuses the IP-based tunnel (for example a Squid hostname allowlist) makes the fetch fail
closed; there is no direct fallback. Policy refusals are logged as `proxy_denied`, while proxy
connection failures are reported as transport errors.

The Node API uses the same setting and rules (`src/libs/utils/outbound-proxy.ts`,
`outbound-http.ts`, installed in `src/index.ts`): a routing dispatcher for global `fetch`, an
`http`/`https.request` hook for clients using the standard Node HTTP stack, and the same
`outbound_http` log fields. Clients that supply their own transport may bypass the hook;
deployment network policy must block direct public connections.

## Embedding model selection

Dense embedding requests use the provider configuration saved in Workspace → AI
Models. The configured provider client uses its configured endpoint, model, and
credentials directly, through the outbound HTTP routing hooks. If no embedding
provider is configured, PipesHub falls back to its local embedding server at
`EMBEDDING_SERVER_URL` (default `http://localhost:8002`). A deployment that does
not run that local server must configure an embedding provider in the app. The
chart profile does not inject a second adapter that overrides that selection.
The baked FastEmbed BM25 cache is separate; it serves the sparse/entity-index
path, not dense embeddings.

## Usage telemetry and Hugging Face

PipesHub's built-in metrics and product-event collection is separate from the
outbound request log. If no saved configuration exists, the Node telemetry
service creates one with collection enabled, a five-minute interval, and the
default collector URL `https://metrics-collector.intellysense.com/collect-metrics`.
The Python services read the same saved configuration and push their metrics
and buffered events to that collector. The app's admin setting is in Workspace
→ General. Turning collection off flushes the current metrics and buffered
events once before saving the opt-out; later periodic pushes stop.

The metrics include route templates, method, status and duration; installation
and process identifiers; organization IDs and email domains; user and
organization counts; authentication methods; connector/activity dimensions;
and configured data-service types. Named events include login/signup, search,
chat/agent runs, answer generation, connector addition, PAT creation, and MCP
connection/tool use. Some event properties include full email addresses, user
IDs, and organization IDs. Chat/search events record modes and counts, not the
query text. MCP events record tool names/client name and version, not tool
arguments.

Opik tracing is a separate optional path. It is active only when the agent
tracing setting is enabled and `OPIK_API_KEY` or `OPIK_URL_OVERRIDE` is
configured. When active, traces can include LLM messages and outputs, tool
arguments, and tool results. Leave those variables unset and tracing disabled
unless that data is intentionally being sent to an Opik endpoint.

FastEmbed's request to
`huggingface.co/api/models/Qdrant/bm25/revision/main` is a model metadata lookup,
not a telemetry event. Hugging Face libraries have a separate opt-out;
`HF_HUB_DISABLE_TELEMETRY=1` disables their usage telemetry. The fork does not
currently set this variable. The deployment image includes the BM25 model, so
keep `FASTEMBED_CACHE_PATH` pointed at the baked cache to avoid runtime model
lookups/downloads.

The observed `mobile.events.data.microsoft.com` request is not referenced by
first-party code or the checked dependency manifests, so this repository scan
does not identify which process or dependency initiates it. Do not add it to an
egress allowlist on the basis of the hostname alone; identify the process before
authorizing it.
