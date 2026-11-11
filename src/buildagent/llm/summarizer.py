"""Bounded summary of history the assembler had to drop.

One non-streaming call per request, fixed model, no tools, no retries. The
helper never runs the agent loop and never returns the SDK exception or the
client itself: callers get either text or a status with a reason code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from openai import AsyncOpenAI

from buildagent.context import estimate, serialize_turns
from buildagent.domain import Message, system_message, user_message
from buildagent.prompts import get_prompt_text

logger = logging.getLogger(__name__)

SUMMARY_MODEL = "gpt-5.6-luna"
SUMMARY_MAX_OUTPUT_TOKENS = 512
SUMMARY_TIMEOUT_S = 10.0
SUMMARY_FRAMING_RESERVE = 1_024
SUMMARY_INPUT_CEILING = 8_192
SUMMARY_PROMPT_NAME = "context_summary"
SUMMARY_PROMPT_LABEL = "production"


@dataclass(frozen=True, slots=True)
class SummaryOutcome:
    """Text on success, otherwise a status plus a fixed reason code."""

    text: str | None
    status: str
    reason: str | None
    omitted_turns: int


def summary_input_limit(budget: int) -> int:
    return min(SUMMARY_INPUT_CEILING, budget - SUMMARY_MAX_OUTPUT_TOKENS - SUMMARY_FRAMING_RESERVE)


def select_turns(turns: list[list[Message]], budget: int) -> tuple[list[list[Message]], int]:
    """Keep the most recent contiguous suffix that fits the summary input limit."""

    limit = summary_input_limit(budget)
    instructions = get_prompt_text(SUMMARY_PROMPT_NAME, SUMMARY_PROMPT_LABEL)
    selected = list(turns)
    while selected:
        messages = _summary_messages(instructions, selected)
        if estimate(messages, []) <= limit:
            return selected, len(turns) - len(selected)
        selected = selected[1:]
    return [], len(turns)


async def summarize_turns(
    client: AsyncOpenAI,
    turns: list[list[Message]],
    budget: int,
) -> SummaryOutcome:
    selected, omitted = select_turns(turns, budget)
    if not selected:
        return SummaryOutcome(None, "skipped", "input_too_large", omitted)

    instructions = get_prompt_text(SUMMARY_PROMPT_NAME, SUMMARY_PROMPT_LABEL)
    messages = _summary_messages(instructions, selected)
    try:
        response = await client.with_options(
            timeout=SUMMARY_TIMEOUT_S, max_retries=0
        ).chat.completions.create(
            model=SUMMARY_MODEL,
            messages=messages,
            max_completion_tokens=SUMMARY_MAX_OUTPUT_TOKENS,
            reasoning_effort="none",
            stream=False,
        )
    except Exception as exc:  # Cancellation is a BaseException and propagates.
        logger.warning("context summary call failed: %s", type(exc).__name__)
        return SummaryOutcome(None, "failed", "api_error", omitted)

    return _read_response(response, omitted)


def _read_response(response: Any, omitted: int) -> SummaryOutcome:
    choices = cast(list[Any], getattr(response, "choices", None) or [])
    if not choices:
        logger.warning("context summary returned no choices")
        return SummaryOutcome(None, "failed", "empty_output", omitted)
    choice = choices[0]
    message = getattr(choice, "message", None)
    if getattr(message, "refusal", None):
        logger.warning("context summary refused")
        return SummaryOutcome(None, "failed", "refusal", omitted)
    if getattr(choice, "finish_reason", None) != "stop":
        logger.warning("context summary finish_reason=%s", getattr(choice, "finish_reason", None))
        return SummaryOutcome(None, "failed", "incomplete_summary", omitted)
    text = getattr(message, "content", None)
    if not isinstance(text, str) or not text.strip():
        logger.warning("context summary returned empty text")
        return SummaryOutcome(None, "failed", "empty_output", omitted)
    return SummaryOutcome(text.strip(), "success", None, omitted)


def _summary_messages(instructions: str, turns: list[list[Message]]) -> list[Message]:
    return [
        system_message(instructions),
        user_message(serialize_turns(turns)),
    ]
