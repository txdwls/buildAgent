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
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from buildagent.agent import TextDelta, ToolStarted, stream_loop
from buildagent.api.dependencies import (
    get_openai_client,
    get_settings_dep,
    get_system_prompt,
    get_tool_registry,
)
from buildagent.api.routes.openai_compat.models import MODEL_ID
from buildagent.config import Settings
from buildagent.domain import Message, system_message
from buildagent.tools import ToolRegistry

router = APIRouter()


class _IncomingMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None


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
) -> StreamingResponse | JSONResponse:
    working_messages = _build_messages(payload, system_prompt)
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if payload.stream:
        return StreamingResponse(
            _sse_stream(
                completion_id=completion_id,
                created=created,
                client=client,
                model=settings.openai_model,
                messages=working_messages,
                tools=tools,
                max_iterations=settings.max_loop_iterations,
            ),
            media_type="text/event-stream",
        )

    content = await _collect_content(
        client=client,
        model=settings.openai_model,
        messages=working_messages,
        tools=tools,
        max_iterations=settings.max_loop_iterations,
    )
    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
    )


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
        messages.append(entry)  # type: ignore[arg-type]
    return messages


def _tool_progress_marker(name: str, arguments_json: str) -> str:
    # Compact one-liner so it renders cleanly in the chat UI.
    compact = arguments_json.replace("\n", " ")
    return f"\n[tool: {name} {compact}]\n"


async def _collect_content(
    client: AsyncOpenAI,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    max_iterations: int,
) -> str:
    parts: list[str] = []
    async for event in stream_loop(
        client=client,
        model=model,
        messages=messages,
        tools=tools,
        max_iterations=max_iterations,
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
) -> AsyncIterator[str]:
    def envelope(delta: dict[str, Any], finish_reason: str | None = None) -> str:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # First chunk announces the role so downstream clients render an assistant turn.
    yield envelope({"role": "assistant", "content": ""})

    async for event in stream_loop(
        client=client,
        model=model,
        messages=messages,
        tools=tools,
        max_iterations=max_iterations,
    ):
        if isinstance(event, TextDelta):
            yield envelope({"content": event.text})
        elif isinstance(event, ToolStarted):
            yield envelope(
                {"content": _tool_progress_marker(event.name, event.arguments_json)}
            )
        # ToolCompleted / LoopCompleted are internal signals: the final answer
        # already incorporates the tool result; nothing to forward as content.

    yield envelope({}, finish_reason="stop")
    yield "data: [DONE]\n\n"
