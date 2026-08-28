"""Message primitives for the agent loop.

Phase 1 uses OpenAI's chat message dict shape directly. `Message` is a
`TypeAlias` for OpenAI's message-param union so the loop code stays
compatible with the SDK. Constructor helpers here shield callers from
having to remember exact key names.

When a second LLM provider is added (Phase 12 fallback), introduce a
provider-neutral wrapper and translate at the `llm/` boundary. Until
then, this indirection would be dead code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageParam,
)

type Message = ChatCompletionMessageParam


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Immutable view of a single tool_call block from an assistant response."""

    id: str
    name: str
    arguments_json: str


def system_message(content: str) -> Message:
    return {"role": "system", "content": content}


def user_message(content: str) -> Message:
    return {"role": "user", "content": content}


def tool_result_message(tool_call_id: str, content: str) -> Message:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def assistant_from_openai(msg: ChatCompletionMessage) -> Message:
    """Convert an OpenAI SDK response message back into a messages-array entry.

    We use `model_dump(exclude_none=True)` so the resulting dict round-trips
    into a subsequent create() call without extra unknown-field noise.
    """

    payload: dict[str, Any] = msg.model_dump(exclude_none=True)
    return payload  # type: ignore[return-value]


def extract_tool_calls(msg: ChatCompletionMessage) -> list[ToolCall]:
    if not msg.tool_calls:
        return []
    calls: list[ToolCall] = []
    for tc in msg.tool_calls:
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        calls.append(ToolCall(id=tc.id, name=fn.name, arguments_json=fn.arguments))
    return calls
