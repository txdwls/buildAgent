"""Registry behavior not covered by filesystem and API tests."""

from __future__ import annotations

from typing import Any

import pytest

from buildagent.domain import Tool, ToolNotFound
from buildagent.tools.registry import ToolRegistry


def _tool(name: str) -> Tool:
    async def handler(_: dict[str, Any]) -> str:
        return name

    return Tool(name=name, description=name, parameters={}, handler=handler)


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(_tool("echo"))

    with pytest.raises(ValueError, match="tool already registered: echo"):
        registry.register(_tool("echo"))


def test_registry_reports_missing_tool() -> None:
    with pytest.raises(ToolNotFound, match="tool not registered: missing"):
        ToolRegistry().get("missing")


def test_registry_reports_empty_state_and_openai_schema() -> None:
    registry = ToolRegistry()
    assert registry.is_empty()
    registry.register(_tool("echo"))
    assert not registry.is_empty()
    assert registry.to_openai_schemas()[0]["function"]["name"] == "echo"
