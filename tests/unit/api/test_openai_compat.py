"""Envelope-shape tests for /v1/chat/completions.

We don't call the real OpenAI SDK — `stream_loop` is monkeypatched to a fake
async generator that yields a deterministic event sequence. The tests then
verify that the route wraps those events into the OpenAI-compatible response
shape correctly for both `stream=true` (SSE) and `stream=false` (single JSON).

DI seams (`get_openai_client`, `get_tool_registry`, `get_system_prompt`) are
overridden so the real Tavily/OpenAI factories are never touched.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from buildagent.agent import LoopCompleted, TextDelta, ToolStarted
from buildagent.api.app import app
from buildagent.api.dependencies import (
    get_openai_client,
    get_system_prompt,
    get_tool_registry,
)
from buildagent.api.routes.openai_compat import chat as chat_module
from buildagent.tools.registry import ToolRegistry


async def _fake_stream_loop(**_: Any) -> AsyncIterator[Any]:
    yield ToolStarted(name="web_search", arguments_json='{"query":"hi"}')
    yield TextDelta(text="hello ")
    yield TextDelta(text="world")
    yield LoopCompleted()


@pytest.fixture(autouse=True)
def _wire_fakes(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setattr(chat_module, "stream_loop", _fake_stream_loop)
    app.dependency_overrides[get_openai_client] = lambda: None
    app.dependency_overrides[get_tool_registry] = ToolRegistry
    app.dependency_overrides[get_system_prompt] = lambda: "sys-prompt"
    yield
    app.dependency_overrides.clear()


def _sse_chunks(body: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = block[len("data: ") :]
        if payload.strip() == "[DONE]":
            continue
        chunks.append(json.loads(payload))
    return chunks


def test_stream_wraps_events_in_openai_sse_envelope() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "buildagent",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert body.endswith("data: [DONE]\n\n")

    chunks = _sse_chunks(body)
    # First chunk announces role so clients render an assistant turn.
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    # Tool progress marker is streamed as a content delta, not a bespoke field.
    joined_content = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks
    )
    assert "[tool: web_search" in joined_content
    assert "hello world" in joined_content
    # Final chunk carries finish_reason=stop.
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_non_stream_returns_single_json_completion() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "buildagent",
                "stream": False,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "buildagent"
    message = body["choices"][0]["message"]
    assert message["role"] == "assistant"
    assert "[tool: web_search" in message["content"]
    assert "hello world" in message["content"]
    assert body["choices"][0]["finish_reason"] == "stop"


def test_models_endpoint_exposes_buildagent_id() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "buildagent"
