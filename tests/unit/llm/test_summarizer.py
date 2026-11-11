"""Bounded history summarization: fixed call shape, input cap, failure codes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from buildagent.domain import Message, system_message, user_message
from buildagent.llm import summarizer
from buildagent.llm.summarizer import (
    SUMMARY_MAX_OUTPUT_TOKENS,
    SUMMARY_MODEL,
    select_turns,
    summarize_turns,
    summary_input_limit,
)


@dataclass
class _Message:
    content: str | None = None
    refusal: str | None = None


@dataclass
class _Choice:
    message: _Message
    finish_reason: str = "stop"


@dataclass
class _Response:
    choices: list[_Choice]


class _Completions:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _Client:
    def __init__(self, result: Any) -> None:
        self.completions = _Completions(result)
        self.chat = self
        self.options: list[dict[str, Any]] = []

    def with_options(self, **kwargs: Any) -> _Client:
        self.options.append(kwargs)
        return self

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.completions.calls


@pytest.fixture(autouse=True)
def _offline_prompt(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def local_prompt(*_: str) -> str:
        return "summarize as data"

    monkeypatch.setattr(summarizer, "get_prompt_text", local_prompt)


def _turn(tag: str, filler: int = 0) -> list[Message]:
    return [
        user_message(f"question {tag} {'x' * filler}"),
        {"role": "assistant", "content": f"answer {tag}"},
    ]


@pytest.mark.asyncio
async def test_successful_summary_uses_the_fixed_call_shape() -> None:
    client = _Client(_Response([_Choice(message=_Message(content="  they chose A  "))]))

    outcome = await summarize_turns(client, [_turn("a"), _turn("b")], 32_768)  # type: ignore[arg-type]

    assert outcome.text == "they chose A"
    assert outcome.status == "success"
    assert outcome.omitted_turns == 0
    call = client.calls[0]
    assert call["model"] == SUMMARY_MODEL
    assert call["max_completion_tokens"] == SUMMARY_MAX_OUTPUT_TOKENS
    assert call["reasoning_effort"] == "none"
    assert call["stream"] is False
    assert "tools" not in call
    assert client.options == [{"timeout": 10.0, "max_retries": 0}]
    # History reaches the model as one user payload, never as tool messages.
    assert [m["role"] for m in call["messages"]] == ["system", "user"]


def test_select_turns_keeps_the_recent_suffix_within_the_input_limit() -> None:
    turns = [_turn(tag, filler=4000) for tag in ("a", "b", "c")]
    selected, omitted = select_turns(turns, 32_768)

    assert omitted == len(turns) - len(selected)
    assert selected == turns[len(turns) - len(selected) :]
    assert summarizer.estimate(
        [system_message("summarize as data"), user_message(summarizer.serialize_turns(selected))],
        [],
    ) <= summary_input_limit(32_768)


@pytest.mark.asyncio
async def test_oversized_source_is_skipped_without_calling_the_model() -> None:
    client = _Client(_Response([_Choice(message=_Message(content="x"))]))
    huge = [[user_message("q" * 40_000), {"role": "assistant", "content": "a"}]]

    outcome = await summarize_turns(client, huge, 8_192)  # type: ignore[arg-type]

    assert outcome.text is None
    assert (outcome.status, outcome.reason) == ("skipped", "input_too_large")
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_Response([_Choice(message=_Message(content=""))]), "empty_output"),
        (_Response([]), "empty_output"),
        (_Response([_Choice(message=_Message(refusal="no"))]), "refusal"),
        (
            _Response([_Choice(message=_Message(content="half"), finish_reason="length")]),
            "incomplete_summary",
        ),
        (TimeoutError("slow"), "api_error"),
    ],
)
async def test_failures_return_a_reason_code_not_an_exception(result: Any, reason: str) -> None:
    client = _Client(result)

    outcome = await summarize_turns(client, [_turn("a")], 32_768)  # type: ignore[arg-type]

    assert outcome.text is None
    assert outcome.status == "failed"
    assert outcome.reason == reason


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    client = _Client(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await summarize_turns(client, [_turn("a")], 32_768)  # type: ignore[arg-type]
