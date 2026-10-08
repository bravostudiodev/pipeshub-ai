# Internal knowledge platform fork

This repository is an independent PipesHub fork adapted into a self-hosted,
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
