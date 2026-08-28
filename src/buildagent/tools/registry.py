from __future__ import annotations

from openai.types.chat import ChatCompletionToolParam

from buildagent.domain import Tool, ToolNotFound


class ToolRegistry:
    """In-memory tool registry. Immutable from the LLM's perspective:
    the loop reads schemas at request time and never mutates the registry
    mid-turn.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFound(name) from exc

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def is_empty(self) -> bool:
        return not self._tools

    def to_openai_schemas(self) -> list[ChatCompletionToolParam]:
        return [tool.to_openai_schema() for tool in self._tools.values()]
