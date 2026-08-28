"""Core function-calling agent loop.

One iteration equals one LLM decision. The loop terminates when the
assistant returns a message with no tool_calls, or when the iteration
budget is exhausted (safety cap against runaway loops).

The @observe decorator wraps the entire loop as one Langfuse trace;
inner LLM calls (via langfuse.openai.AsyncOpenAI) and tool dispatches
(via dispatch_tool_call) contribute nested generations and spans.
"""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
from __future__ import annotations

from langfuse import observe
from openai import AsyncOpenAI

from buildagent.domain import (
    LoopBudgetExceeded,
    Message,
    assistant_from_openai,
    extract_tool_calls,
    tool_result_message,
)
from buildagent.tools import ToolRegistry, dispatch_tool_call


@observe(name="agent.loop", as_type="agent")
async def run_loop(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int = 10,
) -> str:
    working: list[Message] = list(messages)
    for _ in range(max_iterations):
        if tools.is_empty():
            response = await client.chat.completions.create(
                model=model, messages=working
            )
        else:
            response = await client.chat.completions.create(
                model=model, messages=working, tools=tools.to_openai_schemas()
            )
        message = response.choices[0].message
        working.append(assistant_from_openai(message))

        calls = extract_tool_calls(message)
        if not calls:
            return message.content or ""

        for call in calls:
            result = await dispatch_tool_call(tools, call)
            working.append(tool_result_message(call.id, result))

    raise LoopBudgetExceeded(max_iterations)
