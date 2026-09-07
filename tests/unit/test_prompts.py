"""Tests for Langfuse prompt retrieval and the local fallback."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

import pytest

from buildagent import prompts


@pytest.fixture(autouse=True)
def clear_prompt_cache() -> Generator[None, None, None]:
    prompts.get_prompt_text.cache_clear()
    yield
    prompts.get_prompt_text.cache_clear()


def test_get_prompt_text_uses_langfuse_prompt_and_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class _Client:
        def get_prompt(self, name: str, *, label: str) -> SimpleNamespace:
            calls.append((name, label))
            return SimpleNamespace(prompt="remote prompt")

    monkeypatch.setattr(prompts, "get_client", lambda: _Client())

    assert prompts.get_prompt_text("judge", "staging") == "remote prompt"
    assert calls == [("judge", "staging")]


def test_main_agent_uses_fallback_when_langfuse_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> object:
        raise RuntimeError("offline")

    monkeypatch.setattr(prompts, "get_client", fail)

    assert prompts.get_prompt_text("main_agent") == prompts.DEFAULT_SYSTEM_PROMPT


def test_non_main_prompt_reraises_langfuse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> object:
        raise RuntimeError("offline")

    monkeypatch.setattr(prompts, "get_client", fail)

    with pytest.raises(RuntimeError, match="offline"):
        prompts.get_prompt_text("judge")
