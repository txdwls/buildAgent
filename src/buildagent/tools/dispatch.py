# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
from __future__ import annotations

import json
from typing import Any

from langfuse import get_client, observe

from buildagent.domain import ToolCall, ToolError
from buildagent.tools.registry import ToolRegistry


@observe(as_type="tool", capture_input=False, capture_output=False)
async def dispatch_tool_call(registry: ToolRegistry, call: ToolCall) -> str:
    """Run one tool_call and return its string result.

    The @observe decorator creates a Langfuse span; we set name and I/O
    manually so the span reflects the actual tool name and truncated
    payload rather than raw function args.
    """

    lf = get_client()
    lf.update_current_span(
        name=f"tool:{call.name}",
        input={"arguments": call.arguments_json},
    )

    try:
        arguments: dict[str, Any] = json.loads(call.arguments_json or "{}")
    except json.JSONDecodeError as exc:
        error = f"invalid JSON arguments for tool {call.name}: {exc}"
        lf.update_current_span(output={"error": error}, level="ERROR")
        return error

    tool = registry.get(call.name)
    try:
        result = await tool.handler(arguments)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        lf.update_current_span(output={"error": error}, level="ERROR")
        raise ToolError(error) from exc

    lf.update_current_span(output={"result_preview": result[:500]})
    return result
