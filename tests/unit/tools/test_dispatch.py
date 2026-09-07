"""Tests for tool-call parsing, dispatch, and Langfuse status updates."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from buildagent.domain import Tool, ToolCall, ToolError
from buildagent.tools import dispatch as dispatch_module
from buildagent.tools.registry import ToolRegistry


def _tool(name: str, handler: Any) -> Tool:
    return Tool(name=name, description=name, parameters={}, handler=handler)


def _langfuse() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_invalid_json_returns_error_and_marks_span(monkeypatch: pytest.MonkeyPatch) -> None:
    lf = _langfuse()
    monkeypatch.setattr(dispatch_module, "get_client", lambda: lf)

    result = await dispatch_module.dispatch_tool_call(
        ToolRegistry(), ToolCall(id="1", name="echo", arguments_json="{")
    )

    assert result.startswith("invalid JSON arguments for tool echo:")
    assert any(
        call.kwargs.get("level") == "ERROR" for call in lf.update_current_span.call_args_list
    )


@pytest.mark.asyncio
async def test_unknown_tool_is_wrapped_as_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch_module, "get_client", _langfuse)

    with pytest.raises(ToolError, match="tool not registered: missing"):
        await dispatch_module.dispatch_tool_call(
            ToolRegistry(), ToolCall(id="1", name="missing", arguments_json="{}")
        )


@pytest.mark.asyncio
async def test_handler_exception_is_wrapped_as_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch_module, "get_client", _langfuse)

    async def fail(_: dict[str, Any]) -> str:
        raise RuntimeError("broken")

    registry = ToolRegistry()
    registry.register(_tool("explode", fail))

    with pytest.raises(ToolError, match="RuntimeError: broken"):
        await dispatch_module.dispatch_tool_call(
            registry, ToolCall(id="1", name="explode", arguments_json="{}")
        )


@pytest.mark.asyncio
async def test_error_result_marks_span_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    lf = _langfuse()
    monkeypatch.setattr(dispatch_module, "get_client", lambda: lf)

    async def deny(_: dict[str, Any]) -> str:
        return "error: denied"

    registry = ToolRegistry()
    registry.register(_tool("deny", deny))

    assert (
        await dispatch_module.dispatch_tool_call(
            registry, ToolCall(id="1", name="deny", arguments_json="{}")
        )
        == "error: denied"
    )
    assert any(
        call.kwargs.get("level") == "ERROR" for call in lf.update_current_span.call_args_list
    )
