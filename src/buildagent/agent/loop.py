"""Core function-calling agent loop.

One iteration equals one LLM decision. Every OpenAI call is streamed so the
route layer can forward tokens as they arrive; intermediate iterations
accumulate tool_call deltas, execute the tools, then loop.

`stream_loop` is the primitive that yields events (text tokens, tool progress,
completion). `run_loop` buffers the text deltas and returns a single string
for callers (CLI, tests) that don't need progressive output.

The @observe decorator wraps the loop as one Langfuse trace; inner LLM calls
via `langfuse.openai.AsyncOpenAI` and tool dispatches via `dispatch_tool_call`
contribute nested generations and spans automatically.
"""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langfuse import observe
from openai import AsyncOpenAI

from buildagent.agent.events import (
    LoopCompleted,
    LoopEvent,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)
from buildagent.domain import (
    LoopBudgetExceeded,
    Message,
    ToolCall,
    tool_result_message,
)
from buildagent.tools import ToolRegistry, dispatch_tool_call

# OpenAI's reasoning-family models default to reasoning_effort != 'none' and
# reject function tools on /v1/chat/completions unless we opt out. Non-reasoning
# models reject the parameter entirely, so only send it for known families.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(_REASONING_MODEL_PREFIXES)


@observe(name="agent.stream_loop", as_type="agent")
async def stream_loop(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int = 10,
) -> AsyncIterator[LoopEvent]:
    working: list[Message] = list(messages)
    for _ in range(max_iterations):
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": working,
            "stream": True,
        }
        if not tools.is_empty():
            create_kwargs["tools"] = tools.to_openai_schemas()
            if _is_reasoning_model(model):
                create_kwargs["reasoning_effort"] = "none"

        stream = await client.chat.completions.create(**create_kwargs)

        content_parts: list[str] = []
        # Preserve insertion order via list of {index, id, name, arguments} slots.
        tool_slots: dict[int, dict[str, str]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                text = delta.content
                content_parts.append(text)
                yield TextDelta(text=text)
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = getattr(tc, "index", 0) or 0
                    slot = tool_slots.setdefault(
                        idx, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments

        working.append(_assistant_message(content_parts, tool_slots))

        if not tool_slots:
            yield LoopCompleted()
            return

        for slot in tool_slots.values():
            call = ToolCall(
                id=slot["id"],
                name=slot["name"],
                arguments_json=slot["arguments"],
            )
            yield ToolStarted(name=call.name, arguments_json=call.arguments_json)
            result = await dispatch_tool_call(tools, call)
            yield ToolCompleted(name=call.name, result=result)
            working.append(tool_result_message(call.id, result))

    raise LoopBudgetExceeded(max_iterations)


async def run_loop(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int = 10,
) -> str:
    """Buffered wrapper for callers that only need the final answer text."""

    parts: list[str] = []
    async for event in stream_loop(
        client=client,
        model=model,
        messages=messages,
        tools=tools,
        max_iterations=max_iterations,
    ):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    return "".join(parts)


def _assistant_message(
    content_parts: list[str], tool_slots: dict[int, dict[str, str]]
) -> Message:
    """Rebuild the assistant turn for the next iteration's messages array."""

    msg: dict[str, Any] = {"role": "assistant"}
    content = "".join(content_parts)
    if content:
        msg["content"] = content
    if tool_slots:
        msg["tool_calls"] = [
            {
                "id": slot["id"],
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot["arguments"],
                },
            }
            for slot in tool_slots.values()
        ]
    return msg  # type: ignore[return-value]
