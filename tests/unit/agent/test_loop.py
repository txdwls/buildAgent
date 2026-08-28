"""Tests the core function-calling loop against a stubbed LLM client.

We fake AsyncOpenAI just enough to script a sequence of responses:
first a tool_call, then a plain content answer. The registered tool
records that it was invoked. This verifies that:
    - tool_calls are dispatched
    - tool results are appended as role=tool messages
    - the loop terminates on the first response without tool_calls
    - LoopBudgetExceeded fires when the model keeps calling tools
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from buildagent.agent import run_loop
from buildagent.domain import LoopBudgetExceeded, Tool, user_message
from buildagent.tools.registry import ToolRegistry


@dataclass
class _FakeFunction:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunction
    type: str = "function"


@dataclass
class _FakeMessage:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[_FakeToolCall] | None = None

    def model_dump(self, exclude_none: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            data["content"] = self.content
        if self.tool_calls is not None:
            data["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in self.tool_calls
            ]
        return data


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]


class _FakeCompletions:
    def __init__(self, scripted: list[_FakeMessage]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if not self._scripted:
            raise AssertionError("LLM called more times than scripted")
        return _FakeResponse(choices=[_FakeChoice(message=self._scripted.pop(0))])


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, scripted: list[_FakeMessage]) -> None:
        self._completions = _FakeCompletions(scripted)
        self.chat = _FakeChat(self._completions)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._completions.calls


def _echo_tool(record: list[dict[str, Any]]) -> Tool:
    async def handler(arguments: dict[str, Any]) -> str:
        record.append(arguments)
        return f"echo:{arguments.get('text', '')}"

    return Tool(
        name="echo",
        description="Echoes input for tests",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=handler,
    )


@pytest.mark.asyncio
async def test_loop_dispatches_tool_then_terminates() -> None:
    scripted = [
        _FakeMessage(
            content=None,
            tool_calls=[
                _FakeToolCall(id="c1", function=_FakeFunction("echo", json.dumps({"text": "hi"})))
            ],
        ),
        _FakeMessage(content="done"),
    ]
    client = _FakeClient(scripted)
    called: list[dict[str, Any]] = []
    tools = ToolRegistry()
    tools.register(_echo_tool(called))

    answer = await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=[user_message("hello")],
        tools=tools,
        max_iterations=5,
    )

    assert answer == "done"
    assert called == [{"text": "hi"}]
    assert len(client.calls) == 2
    second_messages = client.calls[1]["messages"]
    assert any(m.get("role") == "tool" and m.get("content") == "echo:hi" for m in second_messages)


@pytest.mark.asyncio
async def test_loop_raises_when_budget_exhausted() -> None:
    tool_call = _FakeToolCall(
        id="loop",
        function=_FakeFunction("echo", json.dumps({"text": "x"})),
    )
    scripted = [_FakeMessage(content=None, tool_calls=[tool_call]) for _ in range(3)]
    client = _FakeClient(scripted)
    tools = ToolRegistry()
    tools.register(_echo_tool([]))

    with pytest.raises(LoopBudgetExceeded):
        await run_loop(
            client=client,  # type: ignore[arg-type]
            model="fake",
            messages=[user_message("hi")],
            tools=tools,
            max_iterations=3,
        )
