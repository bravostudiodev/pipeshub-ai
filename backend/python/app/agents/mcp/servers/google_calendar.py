"""Google Calendar MCP server template — official remote server (Streamable HTTP), OAuth-only."""
from app.agents.mcp.mcp_server_decorator import mcp_server
from app.agents.mcp.models import AuthHint, MCPAuthMode, MCPServerTemplate, MCPTransport


@mcp_server(
    MCPServerTemplate(
        type_id="google_calendar",
        display_name="Google Calendar",
        description="Read calendars and events and check availability in a Google Calendar account.",
        icon="/icons/connectors/calendar.svg",
        transport=MCPTransport.STREAMABLE_HTTP,
        default_auth_mode=MCPAuthMode.OAUTH,
        supported_auth_modes=[MCPAuthMode.OAUTH],
        default_url="https://calendarmcp.googleapis.com/mcp/v1",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        # Google's documented Calendar MCP consent scopes are read-only. The remote
        # MCP may advertise write tools, but these credentials do not grant write access.
        default_scopes=[
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.freebusy",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ],
        authorization_params={"access_type": "offline", "prompt": "consent"},
        supports_dcr=False,
        documentation_url="https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
        auth_hint=AuthHint(
            label="Google OAuth",
            help_text=(
                "Enable the Google Calendar API and Google Calendar MCP API in your Google Cloud "
                "project, then create a Web application OAuth client and provide its client ID "
                "and secret in the MCP server settings."
            ),
        ),
        tags=["calendar", "productivity"],
    )
)
class GoogleCalendarMCPServer:
    """Marker class — see `mcp_template` for the registered catalog entry."""
