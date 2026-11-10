# Chat without indexed-knowledge search

The fork's chat should use connected live services for company-source questions
and must not prefetch or search indexed knowledge. Connector ingestion and its
administration are unchanged; this is a chat policy, not a change to connector
sync jobs. Existing indexed data is not deleted. User-uploaded attachments and
chat history remain available, and graph-backed authentication and attachment
access checks still apply.

The chat-mode bridge suppresses indexed prefetch even for legacy modes. The
agent factory clears indexed knowledge grants before tool registration, and
prevents dynamic full-record registration when knowledge is unavailable.
Attachment history continues to be rehydrated into conversation context; if
full content is unavailable, the assistant asks for reattachment instead of
using indexed record retrieval. The composer no longer offers an Internal
Search toggle. Existing MCP discovery and per-user credential checks remain
unchanged. Public web access remains controlled by the existing Labs setting
and Web Search toggle.

Check both normal and scoped agent chat, lazy/composed grants, attachment
follow-ups, per-user MCP denial, and legacy modes. Live MCP behavior still
requires verification with a running deployment.
