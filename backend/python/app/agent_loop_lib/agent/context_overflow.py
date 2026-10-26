"""One conservative recovery for a provider-rejected context window."""

from __future__ import annotations

from app.agent_loop_lib.core.exceptions import TransportError
from app.agent_loop_lib.core.messages import UserMessage
from app.agent_loop_lib.core.tokens import count_tokens
from app.agent_loop_lib.core.types import Message, MessageRole
from app.agent_loop_lib.hooks.middleware.builtin.loop_compaction import (
    _extract_artifact_ids,
    _extract_prior_summary_lines,
    _extract_turn_summary,
    _is_compaction_summary,
)

_CONTEXT_LIMIT_HINTS = (
    "context_length_exceeded",
    "context length exceeded",
    "maximum context length",
    "context window exceeded",
)


def is_context_overflow(exc: Exception) -> bool:
    """Do not compact on a generic 413, a rate limit, or unstructured provider prose."""
    return (
        isinstance(exc, TransportError)
        and exc.status_code in (400, 413)
        and any(hint in str(exc).lower() for hint in _CONTEXT_LIMIT_HINTS)
    )


def compact_overflow_history(messages: list[Message]) -> list[Message] | None:
    """Summarize only history before the latest human question; leave this turn intact."""
    latest_user = next(
        (i for i in range(len(messages) - 1, -1, -1)
         if isinstance(messages[i], UserMessage) and not messages[i].injected),
        None,
    )
    if latest_user is None or latest_user < 2:
        return None

    earlier = messages[:latest_user]
    pinned = [msg for msg in earlier if msg.role == MessageRole.SYSTEM]
    compactable = [msg for msg in earlier if msg.role != MessageRole.SYSTEM]
    if not compactable:
        return None
    lines: list[str] = []
    artifacts: list[str] = []
    for msg in compactable:
        artifacts.extend(_extract_artifact_ids(msg))
        if _is_compaction_summary(msg):
            lines.extend(_extract_prior_summary_lines(msg))
        else:
            line = _extract_turn_summary(msg)
            if line:
                lines.append(line)
    if not lines:
        return None
    unique_artifacts = list(dict.fromkeys(artifacts))[:20]
    summary = "[Context recovery: older conversation summarized]\n"
    if unique_artifacts:
        summary += f"[artifacts: {', '.join(unique_artifacts)}]\n"
    summary += "\n".join(lines[-20:])[:4000]
    retry = [*pinned, UserMessage(content=summary, injected=True), *messages[latest_user:]]
    # If the latest turn, system prompt or schemas are the problem, do not replay
    # a request that cannot benefit from summarizing old conversation.
    if count_tokens(retry) >= count_tokens(messages):
        return None
    return retry
