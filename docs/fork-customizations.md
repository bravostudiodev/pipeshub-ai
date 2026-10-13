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
