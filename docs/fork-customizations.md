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

## MCP connection recovery

A temporary discovery, transport or configuration-store failure must not sign
an employee out. Authentication decisions use explicit HTTP/OAuth evidence,
not words such as `401` or `expired` in exception text or the last status seen
by another request on the session. HTTP 403 remains a permission/policy failure,
not an instruction to refresh the OAuth token or widen its scopes.

Chat, manual refresh and background refresh mark a saved OAuth credential as
rejected only after an explicit permanent refresh error from the token endpoint,
and only through an atomic conditional update of the rejected snapshot. A
failed configuration read is propagated rather than mistaken for a missing
credential. Disconnect/reconnect cannot be overwritten by an in-flight refresh
or an old de-authentication verdict.

Refresh uses a shared, expiring configuration-store lease per instance/owner,
plus a bounded local lock. Lease ownership is checked before exchange, rejection
handling and persistence. A caller carrying an old access token reuses a grant
another caller already refreshed. The provider request has a hard deadline;
cancelling chat does not abandon persistence of an already-rotated refresh token.
Saving uses a conditional write retried with backoff inside the lease, never a
second token exchange. If it still fails, or lease ownership cannot be verified after the provider
issued tokens, the process parks the rotation for its next refresh rather than
reusing the provider-invalidated refresh token. Parked tokens are bound to the
original credential generation and token snapshot, so a reconnect or newer
refresh cannot be overwritten even if the refresh-token string is unchanged.
No save occurs under an unverified lease. Legacy grants receive their
credential generation under the refresh lease before any provider exchange,
so catalog migration cannot strand a parked rotation. Store/lock failures
remain temporary errors, not reconnect verdicts.
Records de-authenticated by the older refreshers (`refresh_token_invalid`) still
show "Reconnect needed".
The background refresher preserves its existing refresh floor and rejection
threshold, counts rejections per grant, and leaves no-expiry tokens alone.

The conditional-write abstraction supports Redis, etcd and the in-memory store,
including encrypted wrappers. Redis compares the actual stored bytes in a
single-key Lua operation; etcd uses a revision-checked transaction. Updates keep
existing TTLs/leases; lease release cannot delete another holder's replacement.

New OAuth grants record the issuing client ID and a unique credential generation.
Refresh must match that client instead of switching to a newly configured app.
One previous administrator OAuth client is retained server-side when its client
ID changes; historical secrets are never returned by the configuration API.
Legacy grants without a client ID retain the existing resolution order until
refreshed or reconnected. A callback reports success only after credentials are
saved. No employee setup, scope, provider matching or model-routing changes are
required for this hardening.

Token and header instances cannot use one shared administrator credential
(`useAdminAuth`): saving one is refused, and an existing one is reported to the
user and model as needing per-user sign-in, never as a temporary outage. OAuth
is always per user. A service-account agent's MCP sign-in, and its tool catalog
cache, belong to the agent and are shared by everyone who can use that agent;
that is the agent's documented access model, not a per-user credential.

Tool discovery may retry one transient failure automatically; a timeout is not
retried, since it already spent the discovery budget. Opening an
execution session also has bounded recovery, including one OAuth refresh on
401. HTTP evidence is attributed to the individual operation, so a listener or
another in-flight request cannot trigger its authentication retry. A timeout, 429 or 5xx
after sending a call is not blindly replayed: its effect may already have
occurred. Ordinary provider tool errors remain available to the model for
argument correction without changing the user's saved authorization.

### MCP client runtime

The production client now uses the official `mcp==2.3.0` SDK with
`httpx2==2.12.0`, replacing FastMCP. A dedicated task owns each SDK session;
cancelling a tool call does not cancel its siblings or the caller's task scope.
Chat discovery and execution share that session. Expired-session 404s require a
sent session ID; an initial endpoint 404 is not session-expiry evidence. Dead
clients are evicted. OAuth refresh updates healthy session headers instead of
closing unrelated in-flight calls. Only proven unsent requests, refused expired
sessions and operation-attributed authentication refusals can authorize replay.

Usable results survive output-schema mismatches and post-call validation/listing
failures. The protocol error flag is authoritative, not words such as `error` or
`success: false` inside retrieved source content. Mixed text/resource blocks are
preserved; outputs over 200,000 characters are explicitly truncated. Tool-list
pagination must finish; repeated cursors or the 100-page bound fail discovery
rather than silently publishing a partial catalog.

Administrator-only `connectTimeoutSeconds` and `callTimeoutSeconds` overrides
are saved on instance records and represented in OpenAPI/frontend types; no
employee transport settings are added. Omitted update fields preserve an
existing override; explicit null restores defaults. Defaults are 15 seconds to
connect (including URL checks/negotiation), 15 seconds to list, and 60 seconds
without tool progress. `MCP_CONNECT_TIMEOUT_SECONDS` (1–45) and
`MCP_CALL_TIMEOUT_SECONDS` (1–600) override those connection/call defaults.
Progress restarts the call's idle deadline, never its absolute ceiling:
`MCP_TOOL_CALL_MAX_SECONDS` defaults to 1,800 seconds and cannot shorten the
configured idle budget. HTTP reads outlast the call's idle budget. Stop
propagates cancellation; teardown is bounded.

The SDK's HTTP traffic explicitly uses the fork's `select_route` policy,
`OUTBOUND_PROXY_URL`, bypass rules, `SSL_CERT_FILE`/`SSL_CERT_DIR`, sanitized
outbound logging and request correlation. There is no proxy-to-direct fallback.
Direct connections pin validated DNS addresses while retaining Host/TLS SNI;
credentials never follow a different origin. Administrator internal-network
MCP endpoints remain supported by `MCP_ALLOW_PRIVATE_NETWORK_URLS` (default
true), but loopback, link-local and metadata addresses, including embedded IPv4
forms, are blocked. Proxy-only DNS is allowed only after static URL checks.
STDIO retains administrator-configured commands and allowlisted credential env;
the upstream's optional launch restrictions were not adopted.

Rebuild the private Python dependency base **before** an application build with
this runtime; see [`fork-build.md`](fork-build.md). The separate integration
harness retains its FastMCP client for external/legacy MCP compatibility tests;
it is not the production client.

Private MCP catalog caching is integrated in chat execution and the workspace,
agent-builder, and project instance-tool listing APIs. The cache stores complete
provider tool schemas (including input/output schemas and annotations) and server
instructions under an opaque, owner- and generation-bound identity. Cache reads
and fills require fresh instance/credential authority reads; chat session keys
include organization, instance, owner, and scope identity. A catalog cache hit
opens no provider connection during discovery, while first execution opens the
session and revalidates its live listing before sending the tool call. Cache
coordination is process-local with bounded, loop-local locks and listing
limits. A user's tool catalog is kept for 24 hours (`MCP_TOOL_CACHE_TTL_SECONDS`; 0
turns the cache off), or for a shorter server hint. A server hint of 0 or an
unusable hint gets 15 minutes (`MCP_TOOL_CACHE_STALE_TTL_SECONDS`). The live
listing check before the first call keeps a long lifetime safe. The epoch
pointer outlives every entry under it; random, non-reused epoch namespaces
prevent old entries becoming reachable after invalidation or epoch expiry.
Legacy generation migration uses the refresh lease so it cannot strand rotated
refresh tokens. Token refresh preserves an omitted, unchanged scope. Cache
metadata outages permit only authorized live discovery, never cached authority.
Proactive notification-driven shared invalidation remains deferred; first actual
execution validates cached contracts. Legacy shared
admin credentials that lack a per-owner grant remain ineligible and have no
fallback. See the Phase 4 checkpoint in the
[`MCP reliability execution plan`](mcp-reliability-execution-plan.md) for focused
tests and remaining limitations.

Interactive `search_tools` now ranks tools using named app groups and nearby
capability terms, preferring complete app names (Google Drive over an unrelated
Google Calendar tool for a Drive request), while retaining the existing generic
preloading index.
Failed attached MCP sources can surface an unavailable or reconnect diagnostic
without inventing a callable schema, even when another source has matching
tools. Lazy `fetch_tools` declines a whole group that exceeds the remaining
96-tool declaration budget and guides targeted search; search loads only a
bounded number of tools. Turn-time schema projection also caps pre-existing
eager/pinned grants. This is a per-request declaration limit, not an access
control mechanism. Server instructions from a successfully discovered attached instance are
shown as bounded, explicitly untrusted source guidance; they do not authorize
any tool call. MCP schema reference expansion is bounded by depth, node count and expanded
size; malformed or oversized input schemas are skipped at registration rather
than breaking a subsequent model request. The server remains the final input
validator. Assistant auto-attachment retains all authenticated MCP instances,
including duplicate types. Within a request, later duplicate type/name keys get
stable instance-ID-derived tool/group aliases; the first sorted instance keeps
its legacy name. Overlapping type prefixes (such as `foo` and `foo_bar`)
also receive aliases so flattened tool names cannot collide. Provider tool
names that cannot be safely declared as model functions (invalid characters
or over 128 characters) receive bounded, instance-bound aliases without
changing the raw provider call target. Composer MCP selections retain their `instanceId:fullName`
identity through the wire; the backend checks that ID against the attached
instance before filtering by tool name. Legacy bare selections resolve only
to the first instance of a duplicated type, never to both. Stored attachment
raw names still match live discovery for backward compatibility. Project
settings now persist scoped MCP keys; Node intersects exact scoped keys without
stripping instance identity. Existing bare project grants resolve to at most
one first-sorted matching instance (even across colliding type prefixes), and
editing settings migrates them to scoped keys. A stale scoped grant never
silently moves to a different instance. For project chat, an explicit empty
tool selection remains empty at the Node boundary instead of expanding to the
project's default tool set. Full provider/gateway schema compatibility remains
Phase 5 work.

The chat-side project catalog and universal MCP/Actions caches now partition
by the current JWT's user and organization (an absent identity is never
cached). The universal MCP cache also checks the grant-change revision when a
resources panel remounts, so a change made while it was closed is not hidden
behind the five-minute TTL. Successful card OAuth verification, personal-token saves and revokes
invalidate MCP catalogs immediately. In-flight older listings cannot replace
catalogs after identity or grant changes. Project settings and composer lists
refetch on those events; signed-out identity changes clear universal catalog
state. JWT claims partition the browser cache only: the server remains the
authorization source. The employee status payload includes a hash of the caller's random grant
generation (not the generation itself); an OAuth reconnect completes only
after that version changes. Switching identities cancels any in-flight card
popup and clears its personal-token draft. Workspace credential saves/revokes and administrator instance edits now invalidate
browser MCP catalogs after successful changes. The agent builder refreshes personal
MCP entries on those verified events, not on an unverified OAuth window message;
service-account agent credentials continue to refresh only their agent-scoped
sidebar. Old in-flight builder listings cannot replace newer grant or identity
results, and a failed listing shows a load error instead of "no servers".
Remaining Phase 6 OAuth/status integration and live UI verification are pending.

## Chat source lookup

Chat does not prefetch or grant indexed knowledge search, even if an old
client requests it. The agent uses connected live service tools for company
questions; MCP authentication remains per user. The Internal Search toggle is
removed from chat. Graph storage remains in use for identity, permissions,
attachments and other product functions. Connector sync and indexing features
are unchanged and existing indexed data is not deleted. Public web search
retains its existing separate Labs setting and user toggle. Attachment history
is still rehydrated, but the indexed full-record fetch tool is not exposed when
knowledge is disabled; missing attachment content requires reattachment.
See `live-mcp-only-plan.md` for scope and verification.

## Chat image analysis

Chat agent runs register a built-in `analyze_image` tool. Image attachment
references are presented to the text model as hints; execution checks the
persisted conversation through Node's scoped `conversation:image-membership`
service endpoint and independently checks the authenticated caller's record
access before loading the image. The current membership endpoint permits only
caller-owned conversations; shared conversations and service-account uploads
without a human caller's access fail closed. Supplied history is never treated
as membership authority.

The analyzer accepts one PNG, JPEG or WebP stored image per call, at most 5 MiB
and 20 million pixels, and rejects animated images and URLs. It selects the
existing AI Models configuration whose exact model name is
`IMAGE_ANALYSIS_MODEL_NAME` (default `qwen3-vl-32b-instruct`), through the
existing model factory and the configuration's endpoint and credentials.
The model must be marked multimodal and its name must be unique. There is no
fallback to the chat, indexing, or default model. The vision call receives only the image and a fixed description instruction,
not the user's question or chat history. Images are proportionally downscaled
without upscaling to `IMAGE_ANALYSIS_MAX_DIMENSION` (default 1280, allowed
256–2048) before the call. Calls have a 45-second timeout and bounded text
output. `image_analysis` logs record the instruction, model, gateway hostname,
image dimensions and byte counts, outcome, safe error type/status and available
token usage; they never include images, conversation text, credentials, URL
paths or provider responses. HTML and PPTX rendering and visual QA are not provided by this tool and are deferred to
the coding sandbox. See `chat-image-analysis-plan.md` for implementation notes
and remaining verification.

Chat model streaming diagnostics (`llm_stream_start`, `llm_stream_first_chunk`,
`llm_stream_first_event`, and `llm_stream_end`) record per-attempt timing,
chunk and event counts, outcome, and error type without message or tool content.
These describe what the LangChain transport received and yielded, not whether
the browser displayed it. A running stream has no end log until it completes,
fails, or is cancelled.

## Agent context budget and tool exposure

The agent's context budget uses the context length an administrator sets for the
model in AI Models (`contextLength`, carried as `configured_context_window`).
Without it, the built-in model table applies, and unknown models get 128k. The
system prompt and bound tool schemas are reserved before conversation messages
are sized, so auto-compaction and the last-resort guard see the real prompt.
Schemas are estimated at three characters per token. The estimate is a
heuristic: a provider can still reject an oversized request, and there is no
compact-and-retry after such a rejection yet.

At most 96 tool schemas are sent per model call (`MAX_VISIBLE_TOOLS`). A grant
larger than that switches to lazy disclosure, where `search_tools` and
`fetch_tools` load tools on demand, even when lazy disclosure is otherwise off.
Any remaining cut keeps discovery tools and pinned toolsets first and is logged.
The built-in prompt steers the model to focused `search_tools` queries instead
of loading whole toolsets in parallel. `fetch_tools` still returns full schemas
in its result in addition to binding them; that duplicate is a known follow-up.

When the provider explicitly rejects a request for exceeding its context window,
the agent may summarize older conversation history and retry the model call once.
The current user question and its subsequent tool results remain intact; a
partial streamed response, unchanged request size or unrelated payload rejection
is not retried. This shaping is per-call and does not rewrite saved history. If
recovery is not possible or the retry fails, the user sees a fixed message
("This request was too large for the selected model…"). The provider's own text
is logged as `Agent run failed: error_code=... provider_error=...`, never shown.

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
