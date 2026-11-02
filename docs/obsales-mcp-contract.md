# OBSales MCP identity contract snapshot

Observed from the configured `mcp__obsales` server using `describeNamespace` and `describeTool`. This is provider metadata, not a token or CRM data. Reinspect these tools when updating the integration.

The provider namespace states every tool call must include `requesting_user_email`, the person asking, at `@oddbytes.com` or `@chirp.me`. The `crm_guide` parameter description says the email is used for the access log only. The server does not assert this value is independently verified.

- `crm_guide`: required `requesting_user_email: string`
- `search_records`: required `requesting_user_email: string`
- `get_record`: required `requesting_user_email: string`
- `report_funnel`: required `requesting_user_email: string`
- `report_pipeline_summary`: required `requesting_user_email: string`
- `report_stale_deals`: required `requesting_user_email: string`
- `report_recent_changes`: required `requesting_user_email: string`
- `report_followups`: required `requesting_user_email: string`
- `report_revenue`: required `requesting_user_email: string`
- `report_creator_revenue`: required `requesting_user_email: string`
- `report_meetings`: required `requesting_user_email: string`
- `report_leads`: required `requesting_user_email: string`
- `report_leaderboard`: required `requesting_user_email: string`
- `report_scorecard`: required `requesting_user_email: string`
- `search_guides`: required `requesting_user_email: string`
- `report_outreach`: required `requesting_user_email: string`
- `report_today`: required `requesting_user_email: string`
- `get_meeting`: required `requesting_user_email: string`
- `executive_report`: required `requesting_user_email: string`
