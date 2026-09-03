"""Whitelist assembly is trivial split-strip-dedupe, but it gates which model
ids the API accepts, so it earns one runnable check."""

from __future__ import annotations

from buildagent.config.settings import Settings


def _make(**overrides: str) -> Settings:
    # Explicit empty extras so the ambient .env doesn't leak into assertions.
    defaults = {
        "openai_api_key": "k",
        "tavily_api_key": "k",
        "langfuse_public_key": "k",
        "langfuse_secret_key": "k",
        "openai_extra_models": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_whitelist_default_is_single_model() -> None:
    settings = _make(openai_model="gpt-x")
    assert settings.openai_model_whitelist == ["gpt-x"]


def test_whitelist_parses_extra_models_and_dedupes() -> None:
    settings = _make(
        openai_model="gpt-x",
        openai_extra_models="gpt-y, gpt-z , gpt-x",
    )
    assert settings.openai_model_whitelist == ["gpt-x", "gpt-y", "gpt-z"]


def test_whitelist_ignores_empty_entries() -> None:
    settings = _make(openai_model="gpt-x", openai_extra_models=",  ,")
    assert settings.openai_model_whitelist == ["gpt-x"]
