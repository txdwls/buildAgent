"""Message primitives for the agent loop.

Phase 1 used OpenAI's chat message dict shape directly and Phase 2 keeps that
choice: `Message` is a `TypeAlias` for OpenAI's message-param union so both
the buffered loop and the streaming loop can hand messages straight back to
`client.chat.completions.create`.

When a second LLM provider is added (Phase 12 fallback), introduce a
provider-neutral wrapper and translate at the `llm/` boundary. Until then,
this indirection would be dead code.
"""

from __future__ import annotations

from dataclasses import dataclass

from openai.types.chat import ChatCompletionMessageParam

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
