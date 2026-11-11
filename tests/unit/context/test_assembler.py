"""Context assembly budget tests.

The assembler is pure: it takes the working message list plus the tool
schemas and returns a reduced list that fits the request's input estimate.
These tests pin the policies from the Phase 5 design: estimate first, reduce
oversized tool content, then drop the oldest complete turns, never touching
the protected current turn or the caller's original list.
"""

# Messages are OpenAI TypedDict unions; these tests read them as plain dicts.
# pyright: reportGeneralTypeIssues=false, reportTypedDictNotRequiredAccess=false
# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportOperatorIssue=false
from __future__ import annotations

import json
from typing import Any

import pytest

from buildagent.context import (
    MAX_TOOL_CONTENT_BYTES,
    MIN_CONTEXT_BUDGET_TOKENS,
    SUMMARY_OMITTED_NOTICE,
    SUMMARY_PREFIX,
    SUMMARY_RESERVE_UNITS,
    AssemblyResult,
    apply_summary,
    assemble,
    estimate,
    input_limit,
    message_cost,
    validate,
)
from buildagent.domain import GuardrailBlocked, system_message, tool_result_message, user_message

_BUDGET = 8192
# Tool truncation caps content at 4096 bytes, which only fits the default budget.
_BIG_BUDGET = 32_768


def _assistant_call(call_id: str, name: str = "echo", arguments: str = "{}") -> Any:
    return {
        "role": "assistant",
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
        ],
    }


def _turn(tag: str, filler: int = 0) -> list[Any]:
    return [
        user_message(f"question {tag} {'x' * filler}"),
        _assistant_call(f"call-{tag}"),
        tool_result_message(f"call-{tag}", f"result {tag}"),
        {"role": "assistant", "content": f"answer {tag}"},
    ]


def test_short_input_is_returned_unchanged() -> None:
    messages = [system_message("sys"), *_turn("a")]
    result = assemble(messages, [], _BUDGET)

    assert result.messages == messages
    assert result.dropped_turns == []
    assert result.truncated_tool_results == 0
    assert result.input_estimate_before == result.input_estimate_after


def test_estimate_counts_schemas_and_per_message_overhead() -> None:
    messages = [user_message("hi")]
    schemas = [{"type": "function", "function": {"name": "echo", "parameters": {}}}]
    payload = json.dumps(
        {"messages": messages, "tools": schemas}, ensure_ascii=False, separators=(",", ":")
    )
    assert estimate(messages, schemas) == len(payload.encode()) + 16


def test_oversized_tool_content_is_truncated_with_notice_and_keeps_call_id() -> None:
    big = "A" * 60_000 + "TAIL"
    messages = [
        system_message("sys"),
        user_message("go"),
        _assistant_call("c1"),
        tool_result_message("c1", big),
    ]
    result = assemble(messages, [], _BIG_BUDGET)

    tool_msg = result.messages[-1]
    content = tool_msg["content"]
    assert result.truncated_tool_results == 1
    assert tool_msg["tool_call_id"] == "c1"
    assert len(content.encode()) <= MAX_TOOL_CONTENT_BYTES
    assert f"[tool result truncated; original_bytes={len(big.encode())}]" in content
    assert content.startswith("A")
    assert content.endswith("TAIL")
    # The caller's list is never mutated.
    assert messages[-1]["content"] == big


def test_truncation_keeps_utf8_boundaries() -> None:
    big = '한국어 "인용" ' * 6000
    messages = [
        system_message("sys"),
        user_message("go"),
        _assistant_call("c1"),
        tool_result_message("c1", big),
    ]
    result = assemble(messages, [], _BIG_BUDGET)
    content = result.messages[-1]["content"]
    # Round-trips: no replacement characters, no broken sequences.
    assert content.encode().decode() == content
    assert "�" not in content
    assert result.input_estimate_after <= input_limit(_BIG_BUDGET)


def test_oldest_turns_are_dropped_and_current_turn_survives() -> None:
    filler = 3000
    messages: list[Any] = [system_message("sys")]
    for tag in ("a", "b", "c"):
        messages.extend(_turn(tag, filler))
    # Current turn: one assistant with two calls plus both results.
    messages.extend(
        [
            user_message("current question"),
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c-now-1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": "{}"},
                    },
                    {
                        "id": "c-now-2",
                        "type": "function",
                        "function": {"name": "echo", "arguments": "{}"},
                    },
                ],
            },
            tool_result_message("c-now-1", "r1"),
            tool_result_message("c-now-2", "r2"),
        ]
    )

    result = assemble(messages, [], _BUDGET)

    assert result.dropped_turns
    assert result.messages[0] == system_message("sys")
    assert result.messages[1]["content"] == SUMMARY_OMITTED_NOTICE
    assert result.messages[-3]["role"] == "assistant"
    assert [m["tool_call_id"] for m in result.messages[-2:]] == ["c-now-1", "c-now-2"]
    assert any(m.get("content") == "current question" for m in result.messages)
    assert result.input_estimate_after <= input_limit(_BUDGET)
    # No orphan tool results survive.
    ids = {c["id"] for m in result.messages if m.get("tool_calls") for c in m["tool_calls"]}
    assert all(m["tool_call_id"] in ids for m in result.messages if m["role"] == "tool")


def test_protected_region_over_budget_fails_before_any_call() -> None:
    messages = [
        system_message("s" * 20_000),
        user_message("u" * 20_000),
    ]
    with pytest.raises(GuardrailBlocked) as exc:
        assemble(messages, [], _BUDGET)
    assert exc.value.layer == "context"


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param([system_message("s")], id="no-user"),
        pytest.param(
            [user_message("u"), system_message("s")],
            id="late-system",
        ),
        pytest.param(
            [user_message("u"), tool_result_message("x", "r")],
            id="orphan-tool",
        ),
        pytest.param(
            [user_message("u"), _assistant_call("c1")],
            id="missing-result",
        ),
        pytest.param(
            [
                user_message("u"),
                _assistant_call("c1"),
                tool_result_message("c1", "r"),
                tool_result_message("c1", "r"),
            ],
            id="duplicate-result",
        ),
        pytest.param(
            [
                user_message("u"),
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "e", "arguments": {}}}
                    ],
                },
                tool_result_message("c1", "r"),
            ],
            id="non-string-arguments",
        ),
    ],
)
def test_invalid_message_relationships_are_rejected(messages: list[Any]) -> None:
    with pytest.raises(GuardrailBlocked) as exc:
        assemble(messages, [], _BUDGET)
    assert exc.value.layer == "context_input"


def test_apply_summary_replaces_notice_and_falls_back_when_too_large() -> None:
    filler = 3000
    messages: list[Any] = [system_message("sys")]
    for tag in ("a", "b", "c"):
        messages.extend(_turn(tag, filler))
    messages.append(user_message("current question"))

    result = assemble(messages, [], _BUDGET)
    assert result.summary_reserved is True

    ok = apply_summary(result, "earlier talk about a, b, c", [], _BUDGET)
    assert ok[1] == "success"
    assert ok[0][1]["content"].startswith(SUMMARY_PREFIX)

    huge = apply_summary(result, "z" * 50_000, [], _BUDGET)
    # Oversized summaries are trimmed to the reserve rather than blowing the budget.
    assert estimate(ok[0], []) <= input_limit(_BUDGET)
    assert estimate(huge[0], []) <= input_limit(_BUDGET)


def test_result_is_frozen_value() -> None:
    result = assemble([system_message("s"), user_message("u")], [], _BUDGET)
    assert isinstance(result, AssemblyResult)
    with pytest.raises(AttributeError):
        result.budget = 1  # type: ignore[misc]


def test_no_summary_reserve_when_the_request_already_used_its_one_attempt() -> None:
    messages: list[Any] = [system_message("sys")]
    for tag in ("a", "b", "c", "d"):
        messages.extend(_turn(tag, filler=800))
    messages.append(user_message("current question"))

    reserved = assemble(messages, [], _BUDGET)
    unreserved = assemble(messages, [], _BUDGET, can_summarize=False)

    assert reserved.summary_reserved is True
    assert unreserved.summary_reserved is False
    # Holding 2,048 for a summary nobody will request only costs history.
    assert len(unreserved.dropped_turns) < len(reserved.dropped_turns)
    assert len(unreserved.messages) > len(reserved.messages)
    assert unreserved.input_estimate_after <= input_limit(_BUDGET)


def test_escape_heavy_summary_still_respects_its_own_reserve() -> None:
    messages: list[Any] = [system_message("sys")]
    for tag in ("a", "b", "c"):
        messages.extend(_turn(tag, filler=14_000))
    messages.append(user_message("current question"))

    result = assemble(messages, [], _BIG_BUDGET)
    # Quotes and backslashes roughly double once JSON-escaped.
    noisy = '"\\' * 1800
    prepared, status = apply_summary(result, noisy, [], _BIG_BUDGET)

    assert status == "success"
    summary = next(m for m in prepared if m["content"].startswith(SUMMARY_PREFIX))
    assert message_cost(summary) <= SUMMARY_RESERVE_UNITS
    assert estimate(prepared, []) <= input_limit(_BIG_BUDGET)


def test_budget_floor_covers_the_default_tool_schema_cost() -> None:
    # Regression for the 413 seen live at the old 8,192 floor.
    assert input_limit(MIN_CONTEXT_BUDGET_TOKENS) > 4_605


def test_content_that_cannot_be_utf8_encoded_is_invalid_input() -> None:
    with pytest.raises(GuardrailBlocked) as exc:
        validate([user_message("a\ud800b")])
    assert exc.value.layer == "context_input"
