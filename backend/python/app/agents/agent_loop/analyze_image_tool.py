"""Built-in image analysis tool; registration requires trusted membership wiring."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.agent_loop_lib.tools.base import ParameterType, Tool, ToolOutput, ToolParameter
from app.agents.agent_loop.image_analysis_provider import (
    ImageAnalysisUnavailable,
    analyze_authorized_image,
)
from app.agents.agent_loop.image_analysis_resolver import (
    ImageAttachmentUnavailable,
    MembershipCheck,
    resolve_chat_image,
)

if TYPE_CHECKING:
    from app.agents.agent_loop.context import AgentContext


class AnalyzeImageTool(Tool):
    """Analyze a current-conversation image, after independent access checks."""

    def __init__(self, context: AgentContext, membership_check: MembershipCheck) -> None:
        self._context = context
        self._membership_check = membership_check

    @property
    def name(self) -> str:
        return "analyze_image"

    @property
    def short_description(self) -> str:
        return "Visually inspect an image attached to this conversation."

    @property
    def description(self) -> str:
        return (
            "Use this to answer visual questions about an image attached to the current "
            "chat. Supply the attachment's virtual record ID. Returns a general visual "
            "description; use it to answer the user. It cannot render HTML or slides."
        )

    @property
    def path(self) -> str:
        return "/tools/data/analyze_image"

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="attachment_id", type=ParameterType.STRING, required=True,
                          description="Virtual record ID of the current-chat image attachment."),
        ]

    async def execute(self, attachment_id: str, **kwargs: Any) -> ToolOutput:  # noqa: ANN401
        try:
            image = await resolve_chat_image(self._context, attachment_id, self._membership_check)
            finding = await analyze_authorized_image(self._context.config_service, image)
        except ImageAttachmentUnavailable:
            return ToolOutput(success=False, error="This image attachment is unavailable or inaccessible.")
        except ImageAnalysisUnavailable:
            return ToolOutput(success=False, error="The image analysis service is unavailable. Please try again later.")
        except ValueError:
            return ToolOutput(success=False, error="The image is invalid.")
        return ToolOutput(success=True, data=finding)
