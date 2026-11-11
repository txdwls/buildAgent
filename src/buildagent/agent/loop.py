"""Core function-calling agent loop.

One iteration equals one LLM decision. Every OpenAI call is streamed so the
route layer can forward tokens as they arrive; intermediate iterations
accumulate tool_call deltas, execute the tools, then loop.

`stream_loop` is the primitive that yields events (text tokens, tool progress,
completion). `run_loop` buffers the text deltas and returns a single string
for callers (CLI, tests) that don't need progressive output.

The root observation wraps the loop as one Langfuse trace; inner LLM calls
via `langfuse.openai.AsyncOpenAI` and tool dispatches via `dispatch_tool_call`
contribute nested generations and spans automatically.
"""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Any, cast
from uuid import uuid4

from langfuse import get_client, propagate_attributes
from openai import AsyncOpenAI

from buildagent.agent.events import (
    LoopCompleted,
    LoopEvent,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)
from buildagent.context import (
    DEFAULT_CONTEXT_BUDGET_TOKENS,
    ESTIMATOR,
    OUTPUT_RESERVE_TOKENS,
    apply_summary,
    assemble,
    estimate,
)
from buildagent.domain import (
    GuardrailBlocked,
    LoopBudgetExceeded,
    Message,
    ToolCall,
    tool_result_message,
)
from buildagent.llm.summarizer import summarize_turns
from buildagent.observability.tracer import trace_task
from buildagent.tools import ToolRegistry, dispatch_tool_call

# OpenAI's reasoning-family models default to reasoning_effort != 'none' and
# reject function tools on /v1/chat/completions unless we opt out. Non-reasoning
# models reject the parameter entirely, so only send it for known families.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(_REASONING_MODEL_PREFIXES)


async def stream_loop(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int = 10,
    *,
    source: str = "api",
    session_id: str | None = None,
    request_id: str | None = None,
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> AsyncIterator[LoopEvent]:
    """One request is one trace, containing generations and tool observations."""
    lf = get_client()
    request_id = request_id or uuid4().hex
    question = next((m.get("content", "") for m in reversed(messages) if m["role"] == "user"), "")
    task = trace_task(source, question)
    name = f"agent.{source}.{task}"
    tags = [f"source:{source}", f"task:{task}"]
    parts: list[str] = []
    tool_errors = 0
    with (
        lf.start_as_current_observation(name=name, as_type="agent", input=question) as span,
        propagate_attributes(
            trace_name=name,
            session_id=session_id,
            tags=tags,
            metadata={"request_id": request_id, "model": model, "source": source, "task": task},
        ),
    ):
        try:
            async with aclosing(
                _stream_loop(
                    client,
                    model,
                    messages,
                    tools,
                    max_iterations,
                    context_budget_tokens=context_budget_tokens,
                )
            ) as events:
                async for event in events:
                    if isinstance(event, TextDelta):
                        parts.append(event.text)
                    elif isinstance(event, ToolStarted):
                        parts.clear()
                        tag = f"tool:{event.name}"
                        if tag not in tags:
                            tags.append(tag)
                    elif isinstance(event, ToolCompleted) and event.result.lower().startswith(
                        ("error:", "invalid json arguments")
                    ):
                        tool_errors += 1
                    yield event
        except BaseException as exc:
            status = "error" if isinstance(exc, Exception) else "cancelled"
            span.update(
                level="ERROR" if status == "error" else "WARNING",
                status_message=type(exc).__name__,
                output="".join(parts),
            )
            with propagate_attributes(
                tags=[*tags, f"status:{status}"], metadata={"status": status}
            ):
                pass
            raise
        else:
            status = "completed_with_tool_errors" if tool_errors else "completed"
            span.update(
                output="".join(parts),
                level="WARNING" if tool_errors else "DEFAULT",
                metadata={"tool_error_count": tool_errors},
            )
            with propagate_attributes(
                tags=[*tags, f"status:{status}"], metadata={"status": status}
            ):
                pass


async def _stream_loop(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int = 10,
    *,
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> AsyncGenerator[LoopEvent, None]:
    lf = get_client()
    # Fetch schemas once so the estimate and the request see identical bytes.
    schemas: list[Any] = [] if tools.is_empty() else list(tools.to_openai_schemas())
    working: list[Message] = list(messages)
    summary_attempted = False

    for iteration in range(max_iterations):
        prepared, summary_attempted = await _assemble_iteration(
            lf=lf,
            client=client,
            working=working,
            schemas=schemas,
            budget=context_budget_tokens,
            iteration=iteration,
            summary_attempted=summary_attempted,
        )
        working = list(prepared)

        create_kwargs: dict[str, Any] = {
            "model": model,
            # A fresh list: later appends must not rewrite this call's arguments.
            "messages": list(working),
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": OUTPUT_RESERVE_TOKENS,
        }
        if schemas:
            create_kwargs["tools"] = schemas
            if _is_reasoning_model(model):
                create_kwargs["reasoning_effort"] = "none"

        stream = await client.chat.completions.create(**create_kwargs)

        content_parts: list[str] = []
        # Preserve insertion order via list of {index, id, name, arguments} slots.
        tool_slots: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage: Any = None

        async for chunk in stream:
            usage = getattr(chunk, "usage", None) or usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = choice.delta
            if getattr(delta, "content", None):
                text = delta.content
                content_parts.append(text)
                yield TextDelta(text=text)
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = getattr(tc, "index", 0) or 0
                    slot = tool_slots.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments

        _record_usage(lf, usage, iteration)

        # Truncated generations may carry half-written tool arguments: never
        # dispatch them and never present the partial text as a finished answer.
        if finish_reason not in ("stop", "tool_calls"):
            raise GuardrailBlocked("generation", f"finish_reason={finish_reason or 'missing'}")
        if finish_reason == "tool_calls" and not tool_slots:
            raise GuardrailBlocked("generation", "finish_reason=tool_calls without tool calls")
        _check_generated_calls(tool_slots, working)

        working.append(_assistant_message(content_parts, tool_slots))

        if not tool_slots:
            yield LoopCompleted()
            return

        for slot in tool_slots.values():
            call = ToolCall(
                id=slot["id"],
                name=slot["name"],
                arguments_json=slot["arguments"],
            )
            yield ToolStarted(name=call.name, arguments_json=call.arguments_json)
            result = await dispatch_tool_call(tools, call)
            yield ToolCompleted(name=call.name, result=result)
            working.append(tool_result_message(call.id, result))

    raise LoopBudgetExceeded(max_iterations)


async def _assemble_iteration(
    lf: Any,
    client: AsyncOpenAI,
    working: list[Message],
    schemas: list[Any],
    budget: int,
    iteration: int,
    summary_attempted: bool,
) -> tuple[list[Message], bool]:
    """Fit the next request into the budget, summarizing at most once per request."""

    with lf.start_as_current_observation(name="context.assemble", as_type="span") as span:
        result = assemble(working, schemas, budget, can_summarize=not summary_attempted)
        prepared = result.messages
        summary_status = "not_needed"
        summary_reason: str | None = None
        omitted_turns = 0

        if result.dropped_turns and result.summary_reserved and not summary_attempted:
            summary_attempted = True
            outcome = await summarize_turns(client, result.dropped_turns, budget)
            omitted_turns = outcome.omitted_turns
            if outcome.text is None:
                summary_status = outcome.status
                summary_reason = outcome.reason
            else:
                prepared, summary_status = apply_summary(result, outcome.text, schemas, budget)
                if summary_status != "success":
                    summary_reason = "summary_does_not_fit"
        elif result.dropped_turns:
            summary_status = "skipped"
            summary_reason = "already_attempted" if summary_attempted else "no_summary_reserve"

        span.update(
            metadata={
                "estimator": ESTIMATOR,
                "iteration": iteration,
                "budget": result.budget,
                "output_reserve": OUTPUT_RESERVE_TOKENS,
                "input_estimate_before": result.input_estimate_before,
                # The estimate of what actually goes to the provider, after any
                # summary insertion, so it lines up with the reported usage.
                "input_estimate_after": estimate(prepared, schemas),
                "schema_bytes": result.schema_bytes,
                "messages_before": result.messages_before,
                "messages_after": len(prepared),
                "truncated_tool_results": result.truncated_tool_results,
                "dropped_turns": len(result.dropped_turns),
                "summary_status": summary_status,
                "summary_reason": summary_reason,
                "summary_source_omitted_turns": omitted_turns,
            }
        )
    return prepared, summary_attempted


def _record_usage(lf: Any, usage: Any, iteration: int) -> None:
    """Record provider-reported usage; a missing usage chunk records nothing."""

    if usage is None:
        return
    with lf.start_as_current_observation(name="model.usage", as_type="span") as span:
        span.update(
            metadata={
                "iteration": iteration,
                "call": "main",
                "actual_prompt_tokens": getattr(usage, "prompt_tokens", None),
                "actual_completion_tokens": getattr(usage, "completion_tokens", None),
            }
        )


async def run_loop(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int = 10,
    *,
    source: str = "cli",
    session_id: str | None = None,
    request_id: str | None = None,
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> str:
    """Buffered wrapper for callers that only need the final answer text."""

    parts: list[str] = []
    async for event in stream_loop(
        client=client,
        model=model,
        messages=messages,
        tools=tools,
        max_iterations=max_iterations,
        source=source,
        session_id=session_id,
        request_id=request_id,
        context_budget_tokens=context_budget_tokens,
    ):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    return "".join(parts)


def _assistant_message(content_parts: list[str], tool_slots: dict[int, dict[str, str]]) -> Message:
    """Rebuild the assistant turn for the next iteration's messages array."""

    msg: dict[str, Any] = {"role": "assistant"}
    content = "".join(content_parts)
    if content:
        msg["content"] = content
    if tool_slots:
        msg["tool_calls"] = [
            {
                "id": slot["id"],
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot["arguments"],
                },
            }
            for slot in tool_slots.values()
        ]
    return msg  # type: ignore[return-value]


def _check_generated_calls(slots: dict[int, dict[str, str]], history: list[Message]) -> None:
    # The model produced these calls, so a malformed one is a provider defect,
    # not client input; catch it here before the assembler reports context_input.
    prior = {
        call.get("id")
        for message in history
        for call in cast(
            list[dict[str, Any]], cast(dict[str, Any], message).get("tool_calls") or []
        )
    }
    seen: set[str] = set()
    for slot in slots.values():
        if not slot["id"] or not slot["name"]:
            raise GuardrailBlocked("generation", "tool call without id or name")
        if slot["id"] in prior or slot["id"] in seen:
            raise GuardrailBlocked("generation", "reused tool call id")
        seen.add(slot["id"])
