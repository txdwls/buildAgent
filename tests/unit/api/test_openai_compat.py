"""Envelope-shape tests for /v1/chat/completions.

We don't call the real OpenAI SDK — `stream_loop` is monkeypatched to a fake
async generator that yields a deterministic event sequence. The tests then
verify that the route wraps those events into the OpenAI-compatible response
shape correctly for both `stream=true` (SSE) and `stream=false` (single JSON).

DI seams (`get_openai_client`, `get_tool_registry`, `get_system_prompt`) are
overridden so the real Tavily/OpenAI factories are never touched.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from buildagent.agent import LoopCompleted, TextDelta, ToolStarted
from buildagent.api.app import app
from buildagent.api.dependencies import (
    get_openai_client,
    get_settings_dep,
    get_system_prompt,
    get_tool_registry,
)
from buildagent.api.routes.openai_compat import chat as chat_module
from buildagent.domain import GuardrailBlocked
from buildagent.tools.registry import ToolRegistry

_DEFAULT_MODEL = "default-model"
_EXTRA_MODEL = "alt-model"


class _FakeSettings:
    openai_model: ClassVar[str] = _DEFAULT_MODEL
    openai_extra_models: ClassVar[str] = _EXTRA_MODEL
    openai_model_whitelist: ClassVar[list[str]] = [_DEFAULT_MODEL, _EXTRA_MODEL]
    max_loop_iterations: ClassVar[int] = 10
    context_budget_tokens: ClassVar[int] = 32_768


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
    app.dependency_overrides[get_settings_dep] = _FakeSettings
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
                "model": _EXTRA_MODEL,
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
    # SSE envelope echoes the resolved (whitelisted) model on every chunk.
    assert all(c["model"] == _EXTRA_MODEL for c in chunks)
    # Tool progress marker is streamed as a content delta, not a bespoke field.
    joined_content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert "<summary>tool: web_search" in joined_content
    assert "hello world" in joined_content
    # Final chunk carries finish_reason=stop.
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_non_stream_returns_single_json_completion() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": _EXTRA_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == _EXTRA_MODEL
    message = body["choices"][0]["message"]
    assert message["role"] == "assistant"
    assert "<summary>tool: web_search" in message["content"]
    assert "hello world" in message["content"]
    assert body["choices"][0]["finish_reason"] == "stop"


def test_unknown_model_falls_back_to_default() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "not-in-whitelist",
                "stream": False,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    assert response.json()["model"] == _DEFAULT_MODEL


def test_models_endpoint_lists_whitelist() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    ids = [entry["id"] for entry in body["data"]]
    assert ids == [_DEFAULT_MODEL, _EXTRA_MODEL]


@pytest.mark.parametrize("stream", [False, True])
def test_chat_id_reaches_loop(monkeypatch: pytest.MonkeyPatch, stream: bool) -> None:
    calls: list[dict[str, Any]] = []

    async def capture(**kwargs: Any) -> AsyncIterator[Any]:
        calls.append(kwargs)
        yield TextDelta(text="ok")
        yield LoopCompleted()

    monkeypatch.setattr(chat_module, "stream_loop", capture)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"X-OpenWebUI-Chat-Id": "chat-123"},
            json={
                "model": _DEFAULT_MODEL,
                "stream": stream,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert response.status_code == 200
    assert calls[0]["session_id"] == "chat-123"
    assert calls[0]["source"] == "openwebui"
    assert calls[0]["request_id"].startswith("chatcmpl-")


def test_build_messages_owns_system_prompt_and_preserves_tool_metadata() -> None:
    payload = chat_module.ChatRequest.model_validate(
        {
            "model": _DEFAULT_MODEL,
            "messages": [
                {"role": "system", "content": "caller prompt"},
                {
                    "role": "tool",
                    "content": "result",
                    "tool_call_id": "call-1",
                    "name": "web_search",
                },
                {"role": "user", "content": None},
            ],
        }
    )

    messages = chat_module._build_messages(payload, "owned prompt")

    assert messages == [
        {"role": "system", "content": "owned prompt"},
        {
            "role": "tool",
            "content": "result",
            "tool_call_id": "call-1",
            "name": "web_search",
        },
        {"role": "user", "content": ""},
    ]


def _guardrail_loop(layer: str) -> Any:
    async def fake(**_: Any) -> AsyncIterator[Any]:
        yield TextDelta(text="partial")
        raise GuardrailBlocked(layer, "test")

    return fake


@pytest.mark.parametrize(
    ("layer", "status", "code"),
    [
        ("context_input", 400, "invalid_context"),
        ("context", 413, "context_budget_exceeded"),
        ("generation", 502, "incomplete_generation"),
    ],
)
def test_json_maps_guardrail_layers_to_the_error_contract(
    monkeypatch: pytest.MonkeyPatch, layer: str, status: int, code: str
) -> None:
    monkeypatch.setattr(chat_module, "stream_loop", _guardrail_loop(layer))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": _DEFAULT_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert "guardrail" not in error["message"]


def test_sse_ends_with_an_error_event_and_no_stop_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_module, "stream_loop", _guardrail_loop("context"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": _DEFAULT_MODEL,
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    body = response.text
    assert body.endswith("data: [DONE]\n\n")
    chunks = _sse_chunks(body)
    assert chunks[-1]["error"]["code"] == "context_budget_exceeded"
    assert all("error" in c or c["choices"][0]["finish_reason"] is None for c in chunks)


def test_incoming_tool_calls_are_preserved_for_the_shared_loop() -> None:
    captured: list[Any] = []

    async def capture(**kwargs: Any) -> AsyncIterator[Any]:
        captured.append(kwargs["messages"])
        yield TextDelta(text="ok")

    with TestClient(app) as client:
        chat_module.stream_loop = capture  # type: ignore[assignment]
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": _DEFAULT_MODEL,
                "messages": [
                    {"role": "user", "content": "search"},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "web_search", "arguments": '{"q":"x"}'},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call-1", "content": "result"},
                    {"role": "user", "content": "summarize"},
                ],
            },
        )
        chat_module.stream_loop = _fake_stream_loop  # type: ignore[assignment]

    assert response.status_code == 200
    sent = captured[0]
    assert sent[2]["tool_calls"][0]["id"] == "call-1"
    assert sent[2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert sent[3]["tool_call_id"] == "call-1"


def test_malformed_tool_call_shape_is_rejected_by_input_validation() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": _DEFAULT_MODEL,
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "tool_calls": [{"id": "", "type": "function"}]},
                ],
            },
        )
    assert response.status_code == 422


def _crashing_loop(**_: Any) -> AsyncIterator[Any]:
    async def fake() -> AsyncIterator[Any]:
        yield TextDelta(text="partial")
        raise RuntimeError("upstream exploded with secret sk-test")

    return fake()


def test_json_maps_unexpected_loop_failure_to_a_safe_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_module, "stream_loop", _crashing_loop)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": _DEFAULT_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "agent_error"
    assert "sk-test" not in response.text


def test_sse_ends_with_an_error_event_on_unexpected_loop_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_module, "stream_loop", _crashing_loop)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": _DEFAULT_MODEL,
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    assert response.text.endswith("data: [DONE]\n\n")
    assert _sse_chunks(response.text)[-1]["error"]["code"] == "agent_error"
    assert "sk-test" not in response.text


@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize(
    "raw_messages",
    [
        '[{"role":"tool","tool_call_id":"a","content":"x"}]',
        '[{"role":"user","content":"a\\ud800b"}]',
    ],
    ids=["orphan-tool-result", "lone-surrogate"],
)
def test_invalid_input_is_a_400_before_any_streaming(stream: bool, raw_messages: str) -> None:
    body = (
        f'{{"model":"{_DEFAULT_MODEL}","stream":{"true" if stream else "false"},'
        f'"messages":{raw_messages}}}'
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            content=body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_context"
