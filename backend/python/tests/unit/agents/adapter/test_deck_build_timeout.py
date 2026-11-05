"""A deck build must never run under run_code's short default timeout."""

import uuid

from app.agent_loop_lib.sandbox.coding.base import CodeRequest, CodeResult
from app.agent_loop_lib.sandbox.manager import SandboxManager, SandboxType
from app.agents.agent_loop.sandbox_bridge import PipesHubCodingSandboxTool


class _Backend:
    def __init__(self) -> None:
        self.sandbox_id = f"fake-{uuid.uuid4()}"
        self.last_request: CodeRequest | None = None

    async def provision(self) -> None:
        return None

    async def upload_file(self, path: str, content: bytes) -> None:
        return None

    async def execute(self, request: CodeRequest) -> CodeResult:
        self.last_request = request
        return CodeResult(stdout="", stderr="", exit_code=0, language=request.language, duration_ms=1.0)


async def _timeout_for(code: str, timeout: float | None = None) -> float:
    backend = _Backend()
    manager = SandboxManager()
    manager.register_backend_factory(SandboxType.CODING, lambda: backend)
    tool = PipesHubCodingSandboxTool(manager, default_timeout=30.0)
    result = await tool.execute(code=code, language="python", timeout=timeout)
    assert result.success, result.error
    return backend.last_request.timeout


async def test_deck_builds_get_ten_minutes_even_without_a_timeout() -> None:
    code = "import subprocess\nsubprocess.run(['python3', '/opt/slidev/build_deck.py', 'deck', 'out.zip'])"
    assert await _timeout_for(code) == 600.0
    assert await _timeout_for(code, timeout=120) == 600.0
    assert await _timeout_for(code, timeout=900) == 900.0


async def test_other_code_keeps_the_requested_timeout() -> None:
    assert await _timeout_for("print(1)") == 30.0
    assert await _timeout_for("print(1)", timeout=90) == 90.0
