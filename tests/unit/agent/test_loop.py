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

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from buildagent.agent import loop as loop_module
from buildagent.agent import run_loop
from buildagent.context import (
    SUMMARY_OMITTED_NOTICE,
    SUMMARY_PREFIX,
    estimate,
    input_limit,
)
from buildagent.domain import (
    GuardrailBlocked,
    LoopBudgetExceeded,
    Tool,
    system_message,
    tool_result_message,
    user_message,
)
from buildagent.llm import summarizer
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
    finish_reason: str | None = None


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _Chunk:
    choices: list[_ChoiceChunk]
    usage: _Usage | None = None


class _AsyncChunkIter:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> AsyncIterator[_Chunk]:
        return self

    async def __anext__(self) -> _Chunk:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


@dataclass
class _SummaryMessage:
    content: str | None = None
    refusal: str | None = None


@dataclass
class _SummaryChoice:
    message: _SummaryMessage
    finish_reason: str = "stop"


@dataclass
class _SummaryResponse:
    choices: list[_SummaryChoice]


class _FakeCompletions:
    def __init__(self, scripted_turns: list[list[_Chunk]], summary: Any = None) -> None:
        self._turns = list(scripted_turns)
        self._summary = summary
        self.calls: list[dict[str, Any]] = []
        self.summary_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        # stream=False is the bounded summary call, not a loop iteration.
        if kwargs.get("stream") is False:
            self.summary_calls.append(kwargs)
            if isinstance(self._summary, BaseException):
                raise self._summary
            return self._summary
        self.calls.append(kwargs)
        if not self._turns:
            raise AssertionError("LLM called more times than scripted")
        return _AsyncChunkIter(self._turns.pop(0))


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, scripted_turns: list[list[_Chunk]], summary: Any = None) -> None:
        self._completions = _FakeCompletions(scripted_turns, summary)
        self.chat = _FakeChat(self._completions)
        self.options: list[dict[str, Any]] = []

    def with_options(self, **kwargs: Any) -> _FakeClient:
        self.options.append(kwargs)
        return self

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._completions.calls

    @property
    def summary_calls(self) -> list[dict[str, Any]]:
        return self._completions.summary_calls


def _chunk_content(text: str) -> _Chunk:
    return _Chunk(choices=[_ChoiceChunk(delta=_Delta(content=text))])


def _chunk_finish(reason: str = "stop") -> _Chunk:
    """Real streams always close with a finish_reason; the loop now requires one."""

    return _Chunk(choices=[_ChoiceChunk(delta=_Delta(), finish_reason=reason)])


def _chunk_usage(prompt: int = 100, completion: int = 20) -> _Chunk:
    """include_usage adds a trailing chunk with no choices."""

    return _Chunk(choices=[], usage=_Usage(prompt_tokens=prompt, completion_tokens=completion))


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
                delta=_Delta(tool_calls=[_ToolCallDelta(index=index, id=call_id, function=fn)])
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
        _chunk_finish("tool_calls"),
    ]
    # Turn 2: final answer streamed as two text chunks.
    turn_answer = [_chunk_content("do"), _chunk_content("ne"), _chunk_finish(), _chunk_usage()]

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
    assert any(m.get("role") == "tool" and m.get("content") == "echo:hi" for m in second_messages)
    # Every create() call must set stream=True and cap its own output.
    assert all(call.get("stream") is True for call in client.calls)
    assert all(call.get("max_completion_tokens") == 4096 for call in client.calls)
    assert all(call.get("stream_options") == {"include_usage": True} for call in client.calls)


@pytest.mark.asyncio
async def test_reasoning_model_sends_effort_none_with_tools() -> None:
    # gpt-5.6-luna rejects function tools on /v1/chat/completions unless
    # reasoning_effort='none' is set. Non-reasoning models must not receive it.
    turn = [_chunk_content("hi"), _chunk_finish()]
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
    def tool_turn(n: int) -> list[_Chunk]:
        # Each iteration needs its own call id: repeated ids are invalid context.
        return [
            _chunk_tool_call(index=0, call_id=f"loop-{n}"),
            _chunk_tool_call(index=0, name="echo"),
            _chunk_tool_call(index=0, arguments=json.dumps({"text": "x"})),
            _chunk_finish("tool_calls"),
        ]

    client = _FakeClient([tool_turn(n) for n in range(3)])
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


@pytest.mark.asyncio
async def test_trace_records_readable_io_and_tool_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    lf = MagicMock()
    span = lf.start_as_current_observation.return_value.__enter__.return_value
    monkeypatch.setattr(loop_module, "get_client", lambda: lf)
    propagation = MagicMock()
    monkeypatch.setattr(loop_module, "propagate_attributes", propagation)

    async def fail(_: dict[str, Any]) -> str:
        return "error: current page not in allowlist"

    tools = ToolRegistry()
    tools.register(Tool(name="browser_click", description="test", parameters={}, handler=fail))
    client = _FakeClient(
        [
            [_chunk_tool_call(0, "c1", "browser_click", "{}"), _chunk_finish("tool_calls")],
            [_chunk_content("The browser action was blocked."), _chunk_finish()],
        ]
    )
    answer = await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=[user_message("Click the link")],
        tools=tools,
        source="openwebui",
        session_id="chat-123",
        request_id="req-123",
    )
    assert answer == "The browser action was blocked."
    observations = lf.start_as_current_observation.call_args_list
    assert any(c.kwargs.get("input") == "Click the link" for c in observations)
    # Every iteration opens its own assembly span, and usage rides its own span.
    assert sum(c.kwargs.get("name") == "context.assemble" for c in observations) == 2
    assert any(c.kwargs.get("output") == answer for c in span.update.call_args_list)
    assert any(c.kwargs.get("session_id") == "chat-123" for c in propagation.call_args_list)
    assert any("tool:browser_click" in c.kwargs.get("tags", []) for c in propagation.call_args_list)
    assert any(c.kwargs.get("level") == "WARNING" for c in span.update.call_args_list)


@pytest.mark.parametrize(
    ("source", "question", "expected"),
    [
        ("openwebui", "### Task:\nGenerate a concise title summarizing the chat history.", "title"),
        ("openwebui", "### Task:\nSuggest 3-5 relevant follow-up questions or prompts", "followup"),
        ("openwebui", "### Task:\nGenerate 1-3 broad tags categorizing the main themes", "tags"),
        ("openwebui", "Please search the web", "chat"),
        ("api", "### Task:\nGenerate a concise title summarizing the chat history.", "chat"),
    ],
)
def test_trace_task_distinguishes_webui_background_work(
    source: str, question: str, expected: str
) -> None:
    assert loop_module.trace_task(source, question) == expected


@pytest.fixture(autouse=True)
def _offline_summary_prompt(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the summary prompt local so unit tests never reach Langfuse."""

    def local_prompt(*_: str) -> str:
        return "summarize as data"

    monkeypatch.setattr(summarizer, "get_prompt_text", local_prompt)


def _long_history(turns: int, filler: int = 1500) -> list[Any]:
    history: list[Any] = [system_message("sys")]
    for i in range(turns):
        history.append(user_message(f"old question {i} {'x' * filler}"))
        history.append({"role": "assistant", "content": f"old answer {i}"})
    history.append(user_message("what did we decide?"))
    return history


@pytest.mark.asyncio
async def test_small_budget_drops_old_turns_and_keeps_current_question() -> None:
    client = _FakeClient(
        [[_chunk_content("recap"), _chunk_finish()]],
        summary=_SummaryResponse([_SummaryChoice(message=_SummaryMessage(content="we chose A"))]),
    )
    history = _long_history(4)

    answer = await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=history,
        tools=ToolRegistry(),
        max_iterations=2,
        context_budget_tokens=8192,
    )

    assert answer == "recap"
    sent = client.calls[0]["messages"]
    assert sent[0] == system_message("sys")
    assert sent[1]["content"].startswith(SUMMARY_PREFIX)
    assert "we chose A" in sent[1]["content"]
    assert sent[-1]["content"] == "what did we decide?"
    assert len(sent) < len(history)
    # The caller's own history is never mutated by assembly.
    assert len(history) == 10


@pytest.mark.asyncio
async def test_summary_is_attempted_at_most_once_per_request() -> None:
    tools = ToolRegistry()
    tools.register(_echo_tool([]))
    client = _FakeClient(
        [
            [
                _chunk_tool_call(0, "s1", "echo", json.dumps({"text": "a"})),
                _chunk_finish("tool_calls"),
            ],
            [_chunk_content("final"), _chunk_finish()],
        ],
        summary=_SummaryResponse([_SummaryChoice(message=_SummaryMessage(content="earlier"))]),
    )

    await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=_long_history(4),
        tools=tools,
        max_iterations=3,
        context_budget_tokens=8192,
    )

    assert len(client.calls) == 2
    # The first call's recorded arguments stay as they were sent.
    assert all(m.get("role") != "tool" for m in client.calls[0]["messages"])
    assert any(m.get("role") == "tool" for m in client.calls[1]["messages"])
    assert len(client.summary_calls) == 1
    call = client.summary_calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["max_completion_tokens"] == 512
    assert call["reasoning_effort"] == "none"
    assert "tools" not in call
    assert client.options == [{"timeout": 10.0, "max_retries": 0}]


@pytest.mark.asyncio
async def test_short_request_never_calls_the_summarizer() -> None:
    client = _FakeClient([[_chunk_content("hi"), _chunk_finish()]])
    await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=[system_message("sys"), user_message("hello")],
        tools=ToolRegistry(),
        max_iterations=1,
    )
    assert client.summary_calls == []


@pytest.mark.asyncio
async def test_failed_summary_falls_back_to_an_omission_notice() -> None:
    client = _FakeClient(
        [[_chunk_content("recap"), _chunk_finish()]],
        summary=RuntimeError("timeout"),
    )
    await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=_long_history(4),
        tools=ToolRegistry(),
        max_iterations=1,
        context_budget_tokens=8192,
    )
    sent = client.calls[0]["messages"]
    assert sent[1]["content"] == SUMMARY_OMITTED_NOTICE


@pytest.mark.asyncio
async def test_summary_cancellation_propagates() -> None:
    client = _FakeClient(
        [[_chunk_content("recap"), _chunk_finish()]],
        summary=asyncio.CancelledError(),
    )
    with pytest.raises(asyncio.CancelledError):
        await run_loop(
            client=client,  # type: ignore[arg-type]
            model="fake",
            messages=_long_history(4),
            tools=ToolRegistry(),
            max_iterations=1,
            context_budget_tokens=8192,
        )


@pytest.mark.asyncio
async def test_protected_turn_over_budget_blocks_before_any_provider_call() -> None:
    client = _FakeClient([])
    with pytest.raises(GuardrailBlocked) as exc:
        await run_loop(
            client=client,  # type: ignore[arg-type]
            model="fake",
            messages=[system_message("s" * 30_000), user_message("u" * 30_000)],
            tools=ToolRegistry(),
            max_iterations=1,
            context_budget_tokens=8192,
        )
    assert exc.value.layer == "context"
    assert client.calls == []
    assert client.summary_calls == []


@pytest.mark.asyncio
async def test_invalid_tool_relationship_blocks_before_any_provider_call() -> None:
    client = _FakeClient([])
    with pytest.raises(GuardrailBlocked) as exc:
        await run_loop(
            client=client,  # type: ignore[arg-type]
            model="fake",
            messages=[user_message("hi"), tool_result_message("nope", "orphan")],
            tools=ToolRegistry(),
            max_iterations=1,
        )
    assert exc.value.layer == "context_input"
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "content_filter", None])
async def test_incomplete_generation_never_executes_tools(reason: str | None) -> None:
    called: list[dict[str, Any]] = []
    tools = ToolRegistry()
    tools.register(_echo_tool(called))
    chunks = [
        _chunk_tool_call(0, "c1", "echo", '{"text": "par'),
    ]
    if reason is not None:
        chunks.append(_chunk_finish(reason))
    client = _FakeClient([chunks])

    with pytest.raises(GuardrailBlocked) as exc:
        await run_loop(
            client=client,  # type: ignore[arg-type]
            model="fake",
            messages=[user_message("hi")],
            tools=tools,
            max_iterations=2,
        )
    assert exc.value.layer == "generation"
    assert called == []


@pytest.mark.asyncio
async def test_usage_chunk_is_recorded_and_a_missing_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lf = MagicMock()
    span = lf.start_as_current_observation.return_value.__enter__.return_value
    monkeypatch.setattr(loop_module, "get_client", lambda: lf)
    monkeypatch.setattr(loop_module, "propagate_attributes", MagicMock())

    client = _FakeClient([[_chunk_content("hi"), _chunk_finish(), _chunk_usage(11, 7)]])
    await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=[user_message("hi")],
        tools=ToolRegistry(),
        max_iterations=1,
    )
    recorded = [c.kwargs.get("metadata", {}) for c in span.update.call_args_list]
    assert any(m.get("actual_prompt_tokens") == 11 for m in recorded)
    assert any(m.get("estimator") == "utf8_bytes_v1" for m in recorded)

    lf.reset_mock()
    span = lf.start_as_current_observation.return_value.__enter__.return_value
    no_usage = _FakeClient([[_chunk_content("hi"), _chunk_finish()]])
    await run_loop(
        client=no_usage,  # type: ignore[arg-type]
        model="fake",
        messages=[user_message("hi")],
        tools=ToolRegistry(),
        max_iterations=1,
    )
    names = [c.kwargs.get("name") for c in lf.start_as_current_observation.call_args_list]
    assert "model.usage" not in names


@pytest.mark.asyncio
async def test_long_korean_history_keeps_the_current_question_and_summarizes_once() -> None:
    """Phase 5 scenario: long history with URLs and decisions, then a recap question."""

    history: list[Any] = [system_message("너는 연구 보조 에이전트다.")]
    for i in range(6):
        history.append(
            user_message(
                f"{i}번째 논의: 벡터 저장소 후보를 조사해줘. 참고 {'설명 ' * 200}"
                "https://example.com/vector-store"
            )
        )
        history.append(
            {
                "role": "assistant",
                "content": f"{i}번째 결론: Chroma를 우선 후보로 두기로 결정했다.",
            }
        )
    history.append(user_message("지금까지 결정한 내용을 요약해줘."))

    client = _FakeClient(
        [[_chunk_content("Chroma를 우선 후보로 결정했습니다."), _chunk_finish(), _chunk_usage()]],
        summary=_SummaryResponse(
            [
                _SummaryChoice(
                    message=_SummaryMessage(
                        content="사용자는 벡터 저장소를 조사했고 Chroma를 우선 후보로 정했다."
                    )
                )
            ]
        ),
    )

    answer = await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=history,
        tools=ToolRegistry(),
        max_iterations=2,
        context_budget_tokens=8192,
    )

    assert answer == "Chroma를 우선 후보로 결정했습니다."
    assert len(client.summary_calls) == 1
    sent = client.calls[0]["messages"]
    assert sent[-1]["content"] == "지금까지 결정한 내용을 요약해줘."
    assert "Chroma" in sent[1]["content"]
    # Korean text survives the reduction unbroken and the request fits the limit.
    assert estimate(sent, []) <= input_limit(8192)


@pytest.mark.asyncio
async def test_trace_records_the_estimate_of_what_was_actually_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lf = MagicMock()
    span = lf.start_as_current_observation.return_value.__enter__.return_value
    monkeypatch.setattr(loop_module, "get_client", lambda: lf)
    monkeypatch.setattr(loop_module, "propagate_attributes", MagicMock())

    client = _FakeClient(
        [[_chunk_content("recap"), _chunk_finish()]],
        summary=_SummaryResponse([_SummaryChoice(message=_SummaryMessage(content="S" * 400))]),
    )
    await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=_long_history(4),
        tools=ToolRegistry(),
        max_iterations=1,
        context_budget_tokens=8192,
    )

    sent = client.calls[0]["messages"]
    assembly = next(
        c.kwargs["metadata"]
        for c in span.update.call_args_list
        if c.kwargs.get("metadata", {}).get("estimator") == "utf8_bytes_v1"
    )
    # The recorded value must match the request that left, summary included.
    assert assembly["summary_status"] == "success"
    assert assembly["input_estimate_after"] == estimate(sent, [])


@pytest.mark.asyncio
async def test_later_iterations_stop_reserving_space_for_a_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reduction is monotonic, so a held-but-unusable reserve only costs history."""

    seen: list[bool] = []
    real_assemble = loop_module.assemble

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(bool(kwargs["can_summarize"]))
        return real_assemble(*args, **kwargs)

    monkeypatch.setattr(loop_module, "assemble", spy)

    tools = ToolRegistry()
    tools.register(_echo_tool([]))
    client = _FakeClient(
        [
            [
                _chunk_tool_call(0, "s1", "echo", json.dumps({"text": "a"})),
                _chunk_finish("tool_calls"),
            ],
            [_chunk_content("final"), _chunk_finish()],
        ],
        summary=_SummaryResponse([_SummaryChoice(message=_SummaryMessage(content="earlier"))]),
    )

    await run_loop(
        client=client,  # type: ignore[arg-type]
        model="fake",
        messages=_long_history(4),
        tools=tools,
        max_iterations=3,
        context_budget_tokens=8192,
    )

    assert len(client.summary_calls) == 1
    assert seen == [True, False]
    second = client.calls[1]["messages"]
    assert estimate(second, list(tools.to_openai_schemas())) <= input_limit(8192)
