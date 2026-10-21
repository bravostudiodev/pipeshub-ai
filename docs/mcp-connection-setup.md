# MCP connection setup

This guide covers the Google Calendar MCP setup for OddJeeves and the bounded
implementation checklist for adding another hosted MCP connection. MCP calls
run with each employee's own OAuth authorization. Do not configure a shared
user credential.

## Google Calendar: what the administrators need to provide

Google Calendar's hosted MCP service is currently in the Google Workspace
Developer Preview. Confirm the Google Cloud project and Workspace are eligible
for that preview before setting up the connection. Google's current setup guide
is [Configure the Calendar MCP server](https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server).

Ask the Google Cloud project administrator to:

1. Enable the **Google Calendar API** (`calendar-json.googleapis.com`) and
   **Google Calendar MCP API** (`calendarmcp.googleapis.com`) in the approved
   Cloud project. This is a one-time project setup; the app itself only calls
   Google's hosted MCP endpoint.
2. Configure Google Auth Platform's branding and audience. Use **Internal**
   for an organization-only app when available. If policy requires an External
   app, configure the allowed audience/test users as appropriate.
3. Add these Calendar MCP read scopes to the OAuth app's Data Access settings:

   ```text
   https://www.googleapis.com/auth/calendar.calendarlist.readonly
   https://www.googleapis.com/auth/calendar.events.freebusy
   https://www.googleapis.com/auth/calendar.events.readonly
   ```

4. Create an OAuth 2.0 client of type **Web application**. Add this exact
   Authorized redirect URI:

   ```text
   https://jeeves.oddbytes.com/mcp-servers/oauth/callback/
   ```

   The trailing slash is required. If the deployed application origin changes,
   use the callback URL shown in Workspace → MCP Servers instead.
5. Give the OddJeeves workspace administrator the OAuth **client ID** and
   **client secret** through the company's approved secret-sharing method. Do
   not put the secret in chat, a ticket, source control, or a Helm value.
6. If Google Workspace API controls restrict third-party or untrusted OAuth
   apps, allow this OAuth client for the organization and its requested scopes.

The OddJeeves workspace administrator then:

1. Opens **Workspace → MCP Servers** and adds the built-in **Google Calendar**
   catalog entry. The template supplies the hosted endpoint, Google OAuth
   endpoints, and the read-only scopes above.
2. Saves the instance and enters the OAuth client ID and secret in that
   instance's OAuth client configuration. Keep OAuth authentication user-bound;
   do not enable shared administrator authentication.
3. Confirms the configured instance is available in `/chat`. Each employee
   clicks **Connect** on the Google Calendar card and authorizes their own
   Google account.

The chart's Squid allowlist must contain `calendarmcp.googleapis.com`. The
existing `accounts.google.com` and `oauth2.googleapis.com` entries cover the
browser authorization setup and server-side token exchange. Do not add
`calendar-json.googleapis.com` to app egress for this hosted MCP flow: that is
the API service enabled in the Google Cloud project, while the app's request is
to `calendarmcp.googleapis.com`.

The hosted Calendar MCP may advertise tools that create, update, or delete
events. This template requests only Google's documented read scopes, so the
user's OAuth grant does not authorize those write operations. Keep the Google
OAuth Data Access scopes and the MCP instance scopes read-only.

## Custom Slides MCP

The employee chat card uses the existing custom MCP instance named exactly
**Slides**. In Workspace → MCP Servers, configure that custom instance with the
provider-approved HTTPS endpoint, Streamable HTTP transport, OAuth, and user-bound
authorization (do not enable shared administrator authentication). Every
employee then clicks **Connect** on the Slides card and authorizes their own
Google account. The status check only selects a unique custom instance with
those characteristics and the exact name; if none or more than one match, the
card remains unavailable. The card uses the existing Google Slides logo at
`frontend/public/icons/connectors/slides.svg`.

## Adding another MCP connection to this fork

Keep a new connection limited to its provider's official endpoint and the
existing user-bound MCP OAuth path:

1. **Confirm the provider setup.** Record the official MCP URL, supported
   transport, OAuth authorization/token endpoints, exact required scopes,
   whether DCR works, provider-side project/API setup, and the callback URL
   requirement. Prefer provider-documented read-only scopes when the product
   requires read-only access. Do not infer OAuth behavior from an ordinary
   connector or API token integration.
2. **Add a catalog template** under
   `backend/python/app/agents/mcp/servers/`. Set an unambiguous `type_id`,
   official endpoint, user OAuth mode, exact scope list, provider documentation,
   and an existing or intentionally added icon. The registry auto-discovers
   modules in this directory.
3. **Add designated connection status** in
   `backend/python/app/api/routes/mcp_servers.py`. Match the exact HTTPS host,
   path, template `typeId`, transport, and auth mode. Return only configured
   status and the current user's own credential state through
   `_get_designated_mcp_connection`.
4. **Wire the status route through Node** in
   `backend/nodejs/apps/src/modules/mcp_servers/controller/mcp_servers.controller.ts`
   and `routes/mcp_servers.routes.ts`, then document it in
   `backend/nodejs/apps/src/modules/api-docs/pipeshub-openapi.yaml`.
5. **Add the employee connection card** using the shared OAuth card in
   `frontend/app/(main)/chat/components/slack-connection-card.tsx`. Add its
   API method and status type under `frontend/app/(main)/workspace/mcp-servers/`,
   render the button in `frontend/app/(main)/chat/page.tsx`, and add localized
   strings or safe English fallbacks. Keep the action label short and consistent
   with the existing `Connect` / `Reconnect` / `Disconnect` buttons.
6. **Allow only observed, necessary egress.** Add the provider's exact MCP
   hostname to `charts/pipeshub-ai/values.yaml` under
   `outbound.squid.allowedDomains`. Add OAuth/token hosts only if they are not
   already present and the application actually calls them. Do not use broad
   wildcards or allow provider APIs that only the remote MCP server calls.
7. **Update the documentation**: this connection matrix, this setup guide,
   chart README, and chart changelog. Include what the provider administrator
   must enable, the OAuth callback/scopes, the exact Squid host addition, and
   any preview or access limitations.
8. **Verify the wiring** in the relevant Python, Node, and frontend suites;
   inspect the rendered chart allowlist. At runtime, confirm the MCP hostname
   appears in Squid logs and an unrelated public hostname is denied. Never use
   cluster-admin access or apply a chart as part of this code change.

Do not create a second credential flow, shared user token, provider-specific
OAuth callback implementation, or direct app-to-provider API connection when
the hosted MCP and existing OAuth support already cover the use case.
