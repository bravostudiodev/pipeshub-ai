"""Model-visible image references; these hints are never authorization."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext


def image_attachment_references(context: AgentContext) -> list[dict[str, str]]:
    candidates: list[Any] = []
    for turn in context.previous_conversations or []:
        if isinstance(turn, dict) and turn.get("role") == "user_query":
            candidates.extend(turn.get("attachments") or [])
    candidates.extend(context.tool_state.get("attachments") or [])
    images: dict[str, dict[str, str]] = {}
    for attachment in candidates:
        if not isinstance(attachment, dict):
            continue
        mime = attachment.get("mimeType")
        ref = attachment.get("virtualRecordId")
        if not isinstance(mime, str) or not mime.lower().startswith("image/"):
            continue
        if not isinstance(ref, str) or not ref or len(ref) > 128:
            continue
        name = attachment.get("recordName")
        images[ref] = {"id": ref, "name": name[:200] if isinstance(name, str) else "image"}
    return list(images.values())[-30:]
