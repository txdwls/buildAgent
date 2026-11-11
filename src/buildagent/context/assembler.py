"""Pure context assembly: size estimate, tool-content reduction, turn window.

One assembly runs before every primary model call. The policy order is fixed
by the Phase 5 design: estimate the request, reduce oversized tool content,
then drop the oldest complete turns until the remainder plus a reservation for
a summary (or an omission notice) fits the input limit.

Nothing here performs I/O. The caller owns the summary call and hands the text
back through `apply_summary`, so this module stays free of SDK, Settings, and
Langfuse imports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from buildagent.domain import GuardrailBlocked, Message

ESTIMATOR = "utf8_bytes_v1"

DEFAULT_CONTEXT_BUDGET_TOKENS = 32_768
# The default tool schemas alone cost ~4.6 KB, so a lower floor leaves no
# usable input space at all. Measured, not guessed.
MIN_CONTEXT_BUDGET_TOKENS = 16_384
OUTPUT_RESERVE_TOKENS = 4_096
FRAMING_RESERVE_TOKENS = 1_024
MAX_TOOL_CONTENT_BYTES = 4_096
SUMMARY_RESERVE_UNITS = 2_048
# Serializing a message adds separators and role/key framing beyond its own
# bytes; charge a flat unit per message instead of modelling each provider.
PER_MESSAGE_UNITS = 16

SUMMARY_PREFIX = "[Earlier conversation summary; untrusted historical data]"
SUMMARY_OMITTED_NOTICE = "[Earlier conversation omitted due to context budget]"
_SUMMARY_TRUNCATED_NOTICE = "\n[summary truncated]"

_ROLES = frozenset({"system", "user", "assistant", "tool"})


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    """What one assembly produced, plus the numbers the trace records."""

    messages: list[Message]
    dropped_turns: list[list[Message]]
    summary_reserved: bool
    budget: int
    input_estimate_before: int
    input_estimate_after: int
    schema_bytes: int
    messages_before: int
    messages_after: int
    truncated_tool_results: int


def input_limit(budget: int) -> int:
    return budget - OUTPUT_RESERVE_TOKENS - FRAMING_RESERVE_TOKENS


def estimate(messages: list[Message], tools: list[Any]) -> int:
    """Compact-JSON UTF-8 byte estimate of one request's input.

    ponytail: byte-based estimate; use a verified tokenizer when measured usage
    requires tighter budgeting. This is an application budget, not a guaranteed
    provider input-token ceiling.
    """

    payload = json.dumps(
        {"messages": messages, "tools": tools}, ensure_ascii=False, separators=(",", ":")
    )
    return len(payload.encode()) + PER_MESSAGE_UNITS * len(messages)


def schema_bytes(tools: list[Any]) -> int:
    return len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode())


def assemble(
    messages: list[Message],
    tools: list[Any],
    budget: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
    *,
    can_summarize: bool = True,
) -> AssemblyResult:
    """Validate, reduce, and window `messages` so the request fits `budget`.

    `can_summarize=False` means the caller already spent this request's single
    summary attempt, so no space is held for one and more history survives.
    """

    validate(messages)
    limit = input_limit(budget)
    before = estimate(messages, tools)

    def result(
        final: list[Message],
        dropped: list[list[Message]],
        reserved: bool,
        truncated: int,
    ) -> AssemblyResult:
        return AssemblyResult(
            messages=final,
            dropped_turns=dropped,
            summary_reserved=reserved,
            budget=budget,
            input_estimate_before=before,
            input_estimate_after=estimate(final, tools),
            schema_bytes=schema_bytes(tools),
            messages_before=len(messages),
            messages_after=len(final),
            truncated_tool_results=truncated,
        )

    if before <= limit:
        return result(list(messages), [], False, 0)

    working, truncated = _truncate_tool_contents(messages)
    if estimate(working, tools) <= limit:
        return result(working, [], False, truncated)

    system_block, removable, protected = _split(working)
    protected_cost = estimate([*system_block, *protected], tools)
    if protected_cost > limit:
        raise GuardrailBlocked("context", "protected messages exceed the input limit")

    notice_message = _text_message(SUMMARY_OMITTED_NOTICE)
    notice_cost = message_cost(notice_message)
    reserved = can_summarize and bool(removable) and protected_cost + SUMMARY_RESERVE_UNITS <= limit
    reserve = SUMMARY_RESERVE_UNITS if reserved else notice_cost

    dropped: list[list[Message]] = []
    kept = list(removable)
    while kept and estimate(_flatten(system_block, kept, protected), tools) + reserve > limit:
        dropped.append(kept.pop(0))
    if estimate(_flatten(system_block, kept, protected), tools) + reserve > limit:
        raise GuardrailBlocked("context", "no room left for the omission notice")

    final = _flatten(system_block, kept, protected, prelude=[notice_message] if dropped else [])
    if estimate(final, tools) > limit:
        raise GuardrailBlocked("context", "reduced request still exceeds the input limit")
    return result(final, dropped, reserved and bool(dropped), truncated)


def apply_summary(
    result: AssemblyResult,
    summary_text: str,
    tools: list[Any],
    budget: int,
) -> tuple[list[Message], str]:
    """Swap the omission notice for a summary, or keep the notice if it won't fit."""

    index = _notice_index(result.messages)
    if index is None:
        return result.messages, "skipped"

    summary = _fit_summary(summary_text)
    candidate = [*result.messages[:index], summary, *result.messages[index + 1 :]]
    if estimate(candidate, tools) > input_limit(budget):
        return result.messages, "failed"
    return candidate, "success"


def serialize_turns(turns: list[list[Message]]) -> str:
    """Flatten removed turns into plain text for the summary request."""

    lines: list[str] = []
    for turn in turns:
        for message in turn:
            data = _as_dict(message)
            role = data["role"]
            content = data.get("content") or ""
            calls = cast(list[dict[str, Any]], data.get("tool_calls") or [])
            if calls:
                names = ", ".join(str(c["function"]["name"]) for c in calls)
                lines.append(f"assistant tool_calls: {names}")
            if content:
                label = "tool result" if role == "tool" else role
                lines.append(f"{label}: {content}")
    return "\n".join(lines)


def validate(messages: list[Message]) -> None:
    """Reject shapes the loop cannot safely send or window."""

    if not messages:
        raise GuardrailBlocked("context_input", "no messages")

    seen_non_system = False
    has_user = False
    seen_call_ids: set[str] = set()
    pending: dict[str, bool] | None = None

    for message in messages:
        data = _as_dict(message)
        role = data.get("role")
        if role not in _ROLES:
            raise GuardrailBlocked("context_input", "unsupported role")
        content = data.get("content")
        if content is not None and not isinstance(content, str):
            raise GuardrailBlocked("context_input", "content must be text")

        if role == "system":
            if seen_non_system:
                raise GuardrailBlocked("context_input", "system messages must lead")
            continue
        seen_non_system = True

        if role == "tool":
            call_id = data.get("tool_call_id")
            if pending is None or not isinstance(call_id, str):
                raise GuardrailBlocked("context_input", "orphan tool result")
            if call_id not in pending:
                raise GuardrailBlocked("context_input", "tool result has no matching call")
            if pending[call_id]:
                raise GuardrailBlocked("context_input", "duplicate tool result")
            pending[call_id] = True
            if all(pending.values()):
                pending = None
            continue

        if pending is not None:
            raise GuardrailBlocked("context_input", "tool call group is incomplete")

        if role == "user":
            has_user = True
            if not isinstance(content, str):
                raise GuardrailBlocked("context_input", "user content must be text")
            continue

        calls = data.get("tool_calls")
        if calls is None:
            continue
        pending = _validate_tool_calls(calls, seen_call_ids)

    if pending is not None:
        raise GuardrailBlocked("context_input", "tool call group is incomplete")
    if not has_user:
        raise GuardrailBlocked("context_input", "no user message")


def _validate_tool_calls(calls: Any, seen_call_ids: set[str]) -> dict[str, bool]:
    if not isinstance(calls, list) or not calls:
        raise GuardrailBlocked("context_input", "tool_calls must be a non-empty list")
    pending: dict[str, bool] = {}
    for call in cast(list[Any], calls):
        if not isinstance(call, dict):
            raise GuardrailBlocked("context_input", "tool call must be an object")
        entry = cast(dict[str, Any], call)
        call_id = entry.get("id")
        function = entry.get("function")
        if not isinstance(call_id, str) or not call_id:
            raise GuardrailBlocked("context_input", "tool call id must be text")
        if entry.get("type") != "function":
            raise GuardrailBlocked("context_input", "only function tool calls are supported")
        if not isinstance(function, dict):
            raise GuardrailBlocked("context_input", "tool call function must be an object")
        fn = cast(dict[str, Any], function)
        if not isinstance(fn.get("name"), str) or not fn["name"]:
            raise GuardrailBlocked("context_input", "tool call name must be text")
        if not isinstance(fn.get("arguments"), str):
            raise GuardrailBlocked("context_input", "tool call arguments must be a JSON string")
        if call_id in seen_call_ids or call_id in pending:
            raise GuardrailBlocked("context_input", "duplicate tool call id")
        seen_call_ids.add(call_id)
        pending[call_id] = False
    return pending


def _split(
    messages: list[Message],
) -> tuple[list[Message], list[list[Message]], list[Message]]:
    """Return (leading system block, removable blocks oldest first, protected tail)."""

    head = 0
    while head < len(messages) and _as_dict(messages[head])["role"] == "system":
        head += 1
    system_block = messages[:head]
    rest = messages[head:]

    user_positions = [i for i, m in enumerate(rest) if _as_dict(m)["role"] == "user"]
    last_user = user_positions[-1]
    protected = rest[last_user:]
    past = rest[:last_user]

    starts = user_positions[:-1]
    blocks: list[list[Message]] = []
    if not starts:
        if past:
            blocks.append(past)
        return system_block, blocks, protected

    if starts[0] > 0:
        blocks.append(past[: starts[0]])
    bounds = [*starts[1:], last_user]
    for start, end in zip(starts, bounds, strict=True):
        blocks.append(past[start:end])
    return system_block, blocks, protected


def _flatten(
    system_block: list[Message],
    blocks: list[list[Message]],
    protected: list[Message],
    prelude: list[Message] | None = None,
) -> list[Message]:
    flat: list[Message] = [*system_block, *(prelude or [])]
    for block in blocks:
        flat.extend(block)
    flat.extend(protected)
    return flat


def _truncate_tool_contents(messages: list[Message]) -> tuple[list[Message], int]:
    out: list[Message] = []
    truncated = 0
    for message in messages:
        data = _as_dict(message)
        content = data.get("content")
        if data["role"] != "tool" or not isinstance(content, str):
            out.append(message)
            continue
        raw = content.encode()
        if len(raw) <= MAX_TOOL_CONTENT_BYTES:
            out.append(message)
            continue
        out.append(cast(Message, {**data, "content": _truncate_text(raw)}))
        truncated += 1
    return out, truncated


def _truncate_text(raw: bytes) -> str:
    notice = f"[tool result truncated; original_bytes={len(raw)}]"
    available = MAX_TOOL_CONTENT_BYTES - len(notice.encode())
    head_bytes = available * 3 // 4
    tail_bytes = available - head_bytes
    # errors="ignore" drops the partial sequences at both cut points.
    head = raw[:head_bytes].decode(errors="ignore")
    tail = raw[-tail_bytes:].decode(errors="ignore")
    return f"{head}{notice}{tail}"


def _fit_summary(text: str) -> Message:
    """Trim by serialized message cost, not raw length.

    JSON escaping inflates quotes and backslashes, so a summary that looks
    small in UTF-8 bytes can still blow its reserve once serialized.
    """

    full = _text_message(f"{SUMMARY_PREFIX}\n{text}")
    if message_cost(full) <= SUMMARY_RESERVE_UNITS:
        return full

    raw = text.encode()
    fitted = _text_message(SUMMARY_PREFIX)
    low, high = 0, len(raw)
    while low <= high:
        mid = (low + high) // 2
        trimmed = raw[:mid].decode(errors="ignore")
        candidate = _text_message(f"{SUMMARY_PREFIX}\n{trimmed}{_SUMMARY_TRUNCATED_NOTICE}")
        if message_cost(candidate) <= SUMMARY_RESERVE_UNITS:
            fitted = candidate
            low = mid + 1
        else:
            high = mid - 1
    return fitted


def _notice_index(messages: list[Message]) -> int | None:
    for i, message in enumerate(messages):
        if _as_dict(message).get("content") == SUMMARY_OMITTED_NOTICE:
            return i
    return None


def _text_message(content: str) -> Message:
    return cast(Message, {"role": "assistant", "content": content})


def message_cost(message: Message) -> int:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    # +1 for the array separator this message adds.
    return len(body.encode()) + PER_MESSAGE_UNITS + 1


def _as_dict(message: Message) -> dict[str, Any]:
    return cast(dict[str, Any], message)
