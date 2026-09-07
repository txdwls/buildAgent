from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from buildagent.llm import openai_client


def test_build_openai_client_passes_settings(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    settings = SimpleNamespace(openai_api_key="key", openai_request_timeout_s=12.5)
    monkeypatch.setattr(openai_client, "AsyncOpenAI", _FakeClient)

    client = openai_client.build_openai_client(settings)  # type: ignore[arg-type]

    assert isinstance(client, _FakeClient)
    assert calls == [{"api_key": "key", "timeout": 12.5}]
