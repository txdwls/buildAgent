from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openai.types.chat import ChatCompletionToolParam

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class Tool:
    """A single tool exposed to the LLM as an OpenAI function.

    - `parameters` is a JSON Schema object describing the function's args.
    - `handler` receives the parsed arguments dict and returns the tool
      result as a string (the string is what the LLM will read).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_schema(self) -> ChatCompletionToolParam:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
