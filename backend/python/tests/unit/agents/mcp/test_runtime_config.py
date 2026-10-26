"""Runtime timeout overrides and official-SDK tool metadata retain their wire contract."""
from unittest.mock import MagicMock

import pytest
from mcp.types import Tool, ToolAnnotations
from pydantic import ValidationError

from app.agents.mcp.discovery import tool_infos_from_listing
from app.agents.mcp.models import MCPServerInstanceConfig
from app.agents.mcp.service import instance_config_from_dict
from app.api.routes.mcp_servers import _build_instance_record


def payload(**overrides) -> MCPServerInstanceConfig:
    return MCPServerInstanceConfig.model_validate({
        "name": "Provider", "transport": "streamable_http", "authMode": "oauth",
        "url": "https://provider.example/mcp", **overrides,
    })


def build(config, existing=None) -> dict:
    registry = MagicMock()
    registry.get_template.return_value = None
    return _build_instance_record(config, "instance-1", "org-1", "user-1", registry, existing=existing)


@pytest.mark.parametrize("field,value", [
    ("connectTimeoutSeconds", 0), ("connectTimeoutSeconds", 45.1),
    ("callTimeoutSeconds", 0.9), ("callTimeoutSeconds", 600.1),
])
def test_api_rejects_unbounded_or_invalid_timeout_overrides(field, value) -> None:
    with pytest.raises(ValidationError):
        payload(**{field: value})


def test_saved_overrides_reach_runtime_and_omission_preserves_them() -> None:
    first = build(payload(connectTimeoutSeconds=20, callTimeoutSeconds=90))
    saved = build(payload(), existing=first)
    config = instance_config_from_dict(saved)
    assert config.connect_timeout_seconds == 20
    assert config.call_timeout_seconds == 90
    assert saved["connectTimeoutSeconds"] == 20
    assert saved["callTimeoutSeconds"] == 90


def test_explicit_null_restores_environment_defaults() -> None:
    first = build(payload(connectTimeoutSeconds=20, callTimeoutSeconds=90))
    saved = build(payload(connectTimeoutSeconds=None, callTimeoutSeconds=None), existing=first)
    config = instance_config_from_dict(saved)
    assert config.connect_timeout_seconds is None
    assert config.call_timeout_seconds is None


def test_native_tool_schemas_and_annotations_keep_camelcase_wire_shape() -> None:
    config = instance_config_from_dict(build(payload()))
    tool = Tool(
        name="search", input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        annotations=ToolAnnotations(read_only_hint=True),
    )
    info = tool_infos_from_listing([tool], config)[0]
    dumped = info.model_dump(by_alias=True)
    assert dumped["inputSchema"] == tool.input_schema
    assert dumped["annotations"]["readOnlyHint"] is True
    assert dumped["namespacedName"] == "mcp_provider_search"
