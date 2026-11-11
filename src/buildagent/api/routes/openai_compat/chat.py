"""OpenAI-compatible /v1/chat/completions endpoint.

Bridges Open WebUI (and any OpenAI SDK client) to the internal agent loop.
Stream=true is the primary path — text tokens are forwarded as OpenAI SSE
`chat.completion.chunk` deltas; tool progress is rendered inline as content
deltas so the caller sees which tool ran without needing a bespoke UI.

Non-stream requests buffer everything and return one `chat.completion` JSON.
"""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from buildagent.agent import TextDelta, ToolStarted, stream_loop
from buildagent.api.dependencies import (
    get_openai_client,
    get_settings_dep,
    get_system_prompt,
    get_tool_registry,
)
from buildagent.config import Settings
from buildagent.context import validate
from buildagent.domain import GuardrailBlocked, Message, system_message
from buildagent.tools import ToolRegistry

router = APIRouter()


class _IncomingFunction(BaseModel):
    name: str = Field(min_length=1)
    arguments: str


class _IncomingToolCall(BaseModel):
    id: str = Field(min_length=1)
    type: Literal["function"] = "function"
    function: _IncomingFunction


class _IncomingMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    # Preserved so a caller can replay a valid tool conversation; the shared
    # assembler still validates every call/result relationship.
    tool_calls: list[_IncomingToolCall] | None = None


# GuardrailBlocked.layer -> (status, error.type, error.code, safe message).
# Provider and SDK strings never reach the caller.
_ERROR_CONTRACT: dict[str, tuple[int, str, str, str]] = {
    "context_input": (
        400,
        "invalid_request_error",
        "invalid_context",
        "The conversation has an invalid message structure.",
    ),
    "context": (
        413,
        "invalid_request_error",
        "context_budget_exceeded",
        "The request does not fit the context budget.",
    ),
    "generation": (
        502,
        "upstream_error",
        "incomplete_generation",
        "The model response ended before it was complete.",
    ),
}
_AGENT_ERROR: tuple[int, dict[str, Any]] = (
    502,
    {
        "error": {
            "message": "The agent could not complete the request.",
            "type": "upstream_error",
            "code": "agent_error",
        }
    },
)
logger = logging.getLogger(__name__)


def _error_payload(exc: Exception) -> tuple[int, dict[str, Any]]:
    if not isinstance(exc, GuardrailBlocked):
        # Last-resort boundary: details go to the server log, never to the caller.
        logger.error("chat completion failed", exc_info=exc)
        return _AGENT_ERROR
    status, error_type, code, message = _ERROR_CONTRACT.get(
        exc.layer, _ERROR_CONTRACT["generation"]
    )
    return status, {"error": {"message": message, "type": error_type, "code": code}}


class ChatRequest(BaseModel):
    model: str
    messages: list[_IncomingMessage]
    stream: bool = False


@router.post("/v1/chat/completions", response_model=None)
async def create_chat_completion(
    payload: ChatRequest,
    client: Annotated[AsyncOpenAI, Depends(get_openai_client)],
    tools: Annotated[ToolRegistry, Depends(get_tool_registry)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    system_prompt: Annotated[str, Depends(get_system_prompt)],
    chat_id: Annotated[str | None, Header(alias="X-OpenWebUI-Chat-Id", max_length=200)] = None,
    session_id: Annotated[str | None, Header(alias="X-Session-Id", max_length=200)] = None,
) -> StreamingResponse | JSONResponse:
    working_messages = _build_messages(payload, system_prompt)
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    resolved_model = _resolve_model(payload.model, settings)
    try:
        # Reject bad input while a real status code can still be sent.
        validate(working_messages)
    except GuardrailBlocked as exc:
        status, error_body = _error_payload(exc)
        return JSONResponse(error_body, status_code=status)

    if payload.stream:
        return StreamingResponse(
            _sse_stream(
                completion_id=completion_id,
                created=created,
                client=client,
                model=resolved_model,
                messages=working_messages,
                tools=tools,
                max_iterations=settings.max_loop_iterations,
                context_budget_tokens=settings.context_budget_tokens,
                session_id=chat_id or session_id,
                source="openwebui" if chat_id else "api",
            ),
            media_type="text/event-stream",
        )

    try:
        content = await _collect_content(
            client=client,
            model=resolved_model,
            messages=working_messages,
            tools=tools,
            max_iterations=settings.max_loop_iterations,
            context_budget_tokens=settings.context_budget_tokens,
            session_id=chat_id or session_id,
            source="openwebui" if chat_id else "api",
            request_id=completion_id,
        )
    except Exception as exc:
        status, error_body = _error_payload(exc)
        return JSONResponse(error_body, status_code=status)
    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": resolved_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
    )


def _resolve_model(requested: str, settings: Settings) -> str:
    # Whitelist gate: unknown model ids fall back to the default so the loop
    # never forwards an id OpenAI would reject with 404.
    if requested in settings.openai_model_whitelist:
        return requested
    return settings.openai_model


def _build_messages(payload: ChatRequest, system_prompt: str) -> list[Message]:
    messages: list[Message] = [system_message(system_prompt)]
    for m in payload.messages:
        # Skip system messages the caller sent — we control our own prompt.
        if m.role == "system":
            continue
        entry: dict[str, Any] = {"role": m.role, "content": m.content or ""}
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        if m.name:
            entry["name"] = m.name
        if m.tool_calls:
            entry["tool_calls"] = [tc.model_dump() for tc in m.tool_calls]
        messages.append(entry)  # type: ignore[arg-type]
    return messages


def _tool_progress_marker(name: str, arguments_json: str) -> str:
    # Render as a collapsible details block. Open WebUI (and most markdown
    # viewers) render <details>/<summary> as a click-to-expand disclosure,
    # keeping the transcript readable while still surfacing the raw args.
    compact = arguments_json.replace("\n", " ")
    return (
        "\n\n<details>\n"
        f"<summary>tool: {name}</summary>\n\n"
        f"```json\n{compact}\n```\n\n"
        "</details>\n\n"
    )


async def _collect_content(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int,
    context_budget_tokens: int,
    session_id: str | None = None,
    source: str = "api",
    request_id: str | None = None,
) -> str:
    parts: list[str] = []
    async for event in stream_loop(
        client=client,
        model=model,
        messages=messages,
        tools=tools,
        max_iterations=max_iterations,
        context_budget_tokens=context_budget_tokens,
        session_id=session_id,
        source=source,
        request_id=request_id,
    ):
        if isinstance(event, TextDelta):
            parts.append(event.text)
        elif isinstance(event, ToolStarted):
            parts.append(_tool_progress_marker(event.name, event.arguments_json))
    return "".join(parts)


async def _sse_stream(
    completion_id: str,
    created: int,
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int,
    context_budget_tokens: int,
    session_id: str | None = None,
    source: str = "api",
) -> AsyncIterator[str]:
    def envelope(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # First chunk announces the role so downstream clients render an assistant turn.
    yield envelope({"role": "assistant", "content": ""})

    try:
        async for event in stream_loop(
            client=client,
            model=model,
            messages=messages,
            tools=tools,
            max_iterations=max_iterations,
            context_budget_tokens=context_budget_tokens,
            session_id=session_id,
            source=source,
            request_id=completion_id,
        ):
            if isinstance(event, TextDelta):
                yield envelope({"content": event.text})
            elif isinstance(event, ToolStarted):
                yield envelope({"content": _tool_progress_marker(event.name, event.arguments_json)})
            # ToolCompleted / LoopCompleted are internal signals: the final answer
            # already incorporates the tool result; nothing to forward as content.
    except Exception as exc:
        # The 200 header is already sent, so the failure has to ride the stream.
        # No finish_reason=stop: the caller must not read this as a clean end.
        _, payload = _error_payload(exc)
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    yield envelope({}, finish_reason="stop")
    yield "data: [DONE]\n\n"
