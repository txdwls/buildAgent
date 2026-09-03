"""Tests the streaming function-calling loop against a stubbed LLM client.

We fake AsyncOpenAI's streaming shape just enough to script a sequence of
turns. Each turn is a list of chunks (SSE deltas); the fake `create()` returns
an async iterator over those chunks. That mirrors the real SDK contract and
verifies:
    - tool_call deltas across chunks are reassembled and dispatched
    - tool results are appended as role="tool" messages on the next turn
    - the loop terminates when a turn has content only (no tool_calls)
    - text deltas from the final turn are surfaced via `run_loop`'s buffered
      return value
    - LoopBudgetExceeded fires when the model keeps calling tools
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest

from buildagent.agent import run_loop
from buildagent.domain import LoopBudgetExceeded, Tool, user_message
from buildagent.tools.registry import ToolRegistry


@dataclass
class _FnDelta:
    name: str | None = None
    arguments: str | None = None


@dataclass
class _ToolCallDelta:
    index: int
    id: str | None = None
    function: _FnDelta | None = None
    type: str = "function"


@dataclass
class _Delta:
    content: str | None = None
    tool_calls: list[_ToolCallDelta] | None = None


@dataclass
class _ChoiceChunk:
    delta: _Delta


@dataclass
class _Chunk:
    choices: list[_ChoiceChunk]


class _AsyncChunkIter:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> AsyncIterator[_Chunk]:
        return self

    async def __anext__(self) -> _Chunk:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _FakeCompletions:
    def __init__(self, scripted_turns: list[list[_Chunk]]) -> None:
        self._turns = list(scripted_turns)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _AsyncChunkIter:
        self.calls.append(kwargs)
        if not self._turns:
            raise AssertionError("LLM called more times than scripted")
        return _AsyncChunkIter(self._turns.pop(0))


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, scripted_turns: list[list[_Chunk]]) -> None:
        self._completions = _FakeCompletions(scripted_turns)
        self.chat = _FakeChat(self._completions)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._completions.calls


def _chunk_content(text: str) -> _Chunk:
    return _Chunk(choices=[_ChoiceChunk(delta=_Delta(content=text))])


def _chunk_tool_call(
    index: int,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> _Chunk:
    fn = _FnDelta(name=name, arguments=arguments)
    return _Chunk(
        choices=[
            _ChoiceChunk(
                delta=_Delta(
                    tool_calls=[_ToolCallDelta(index=index, id=call_id, function=fn)]
                )
            )
        ]
    )


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
async def test_loop_reassembles_tool_call_deltas_then_streams_answer() -> None:
    # Turn 1: split the tool_call across three deltas (id, then name, then
    # arguments in two pieces) — this is what the OpenAI stream really looks like.
    args_json = json.dumps({"text": "hi"})
    turn_tool = [
        _chunk_tool_call(index=0, call_id="c1"),
        _chunk_tool_call(index=0, name="echo"),
        _chunk_tool_call(index=0, arguments=args_json[: len(args_json) // 2]),
        _chunk_tool_call(index=0, arguments=args_json[len(args_json) // 2 :]),
    ]
    # Turn 2: final answer streamed as two text chunks.
    turn_answer = [_chunk_content("do"), _chunk_content("ne")]

    client = _FakeClient([turn_tool, turn_answer])
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
    assert any(
        m.get("role") == "tool" and m.get("content") == "echo:hi"
        for m in second_messages
    )
    # Every create() call must set stream=True.
    assert all(call.get("stream") is True for call in client.calls)


@pytest.mark.asyncio
async def test_reasoning_model_sends_effort_none_with_tools() -> None:
    # gpt-5.6-luna rejects function tools on /v1/chat/completions unless
    # reasoning_effort='none' is set. Non-reasoning models must not receive it.
    turn = [_chunk_content("hi")]
    tools = ToolRegistry()
    tools.register(_echo_tool([]))

    reasoning = _FakeClient([list(turn)])
    await run_loop(
        client=reasoning,  # type: ignore[arg-type]
        model="gpt-5.6-luna",
        messages=[user_message("hello")],
        tools=tools,
        max_iterations=1,
    )
    assert reasoning.calls[0].get("reasoning_effort") == "none"

    plain = _FakeClient([list(turn)])
    await run_loop(
        client=plain,  # type: ignore[arg-type]
        model="gpt-4o",
        messages=[user_message("hello")],
        tools=tools,
        max_iterations=1,
    )
    assert "reasoning_effort" not in plain.calls[0]


@pytest.mark.asyncio
async def test_loop_raises_when_budget_exhausted() -> None:
    def tool_turn() -> list[_Chunk]:
        return [
            _chunk_tool_call(index=0, call_id="loop"),
            _chunk_tool_call(index=0, name="echo"),
            _chunk_tool_call(index=0, arguments=json.dumps({"text": "x"})),
        ]

    client = _FakeClient([tool_turn() for _ in range(3)])
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
