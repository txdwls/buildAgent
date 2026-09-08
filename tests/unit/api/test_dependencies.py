"""Tests for process-level FastAPI dependency wiring."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from buildagent.api import dependencies
from buildagent.domain import Tool


def _tool(name: str) -> Tool:
    async def handler(_: dict[str, Any]) -> str:
        return name

    return Tool(name=name, description=name, parameters={}, handler=handler)


def test_openai_client_provider_is_cached(monkeypatch: Any) -> None:
    dependencies._client.cache_clear()
    sentinel: Any = object()
    settings = object()
    calls: list[Any] = []

    def get_settings() -> object:
        return settings

    def build_client(value: object) -> Any:
        calls.append(value)
        return sentinel

    monkeypatch.setattr(dependencies, "get_settings", get_settings)
    monkeypatch.setattr(dependencies, "build_openai_client", build_client)

    try:
        assert dependencies.get_openai_client() is sentinel
        assert dependencies.get_openai_client() is sentinel
        assert calls == [settings]
    finally:
        dependencies._client.cache_clear()


def test_tool_registry_provider_builds_all_configured_tools(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dependencies._tools.cache_clear()
    settings = SimpleNamespace(
        tavily_api_key="tavily",
        tavily_max_results=3,
        filesystem_root=tmp_path,
        browser_allowed_url_prefixes="https://example.com/",
        browser_headless=False,
        browser_nav_timeout_s=7.0,
    )
    web_calls: list[tuple[str, int]] = []
    browser_calls: list[tuple[str, bool, float, str | Path]] = []

    def build_web(api_key: str, max_results: int) -> Tool:
        web_calls.append((api_key, max_results))
        return _tool("web_search")

    def build_filesystem(root: str | Path) -> list[Tool]:
        assert root == tmp_path
        return [_tool("fs_read")]

    def build_browser(
        *,
        allowed_url_prefixes: str,
        headless: bool,
        nav_timeout_s: float,
        filesystem_root: str | Path,
    ) -> list[Tool]:
        browser_calls.append(
            (allowed_url_prefixes, headless, nav_timeout_s, filesystem_root)
        )
        return [_tool("browser_open")]

    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "build_web_search_tool", build_web)
    monkeypatch.setattr(dependencies, "build_filesystem_tools", build_filesystem)
    monkeypatch.setattr(dependencies, "build_browser_tools", build_browser)

    try:
        registry = dependencies.get_tool_registry()
        assert registry.names() == ["web_search", "fs_read", "browser_open"]
        assert dependencies.get_tool_registry() is registry
        assert web_calls == [("tavily", 3)]
        assert browser_calls == [("https://example.com/", False, 7.0, tmp_path)]
    finally:
        dependencies._tools.cache_clear()


def test_dependency_getters_return_settings_and_prompt(monkeypatch: Any) -> None:
    settings = SimpleNamespace(system_prompt_name="main", system_prompt_label="test")

    def get_prompt(name: str, label: str) -> str:
        return f"{name}:{label}"

    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_prompt_text", get_prompt)

    assert dependencies.get_settings_dep() is settings
    assert dependencies.get_system_prompt() == "main:test"
