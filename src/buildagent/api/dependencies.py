"""FastAPI dependency wiring.

Concrete instances (settings, OpenAI client, tool registry, system prompt) are
built once per process at import time and reused across requests. The DI seam
lets tests substitute fakes via `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from buildagent.config import Settings, get_settings
from buildagent.llm import build_openai_client
from buildagent.prompts import get_prompt_text
from buildagent.tools import (
    ToolRegistry,
    build_browser_tools,
    build_filesystem_tools,
    build_web_search_tool,
)


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    return build_openai_client(get_settings())


@lru_cache(maxsize=1)
def _tools() -> ToolRegistry:
    registry = ToolRegistry()
    settings = get_settings()
    registry.register(
        build_web_search_tool(
            api_key=settings.tavily_api_key,
            max_results=settings.tavily_max_results,
        )
    )
    for tool in build_filesystem_tools(settings.filesystem_root):
        registry.register(tool)
    for tool in build_browser_tools(
        allowed_url_prefixes=settings.browser_allowed_url_prefixes,
        headless=settings.browser_headless,
        nav_timeout_s=settings.browser_nav_timeout_s,
    ):
        registry.register(tool)
    return registry


def get_settings_dep() -> Settings:
    return get_settings()


def get_openai_client() -> AsyncOpenAI:
    return _client()


def get_tool_registry() -> ToolRegistry:
    return _tools()


def get_system_prompt() -> str:
    settings = get_settings()
    return get_prompt_text(
        name=settings.system_prompt_name,
        label=settings.system_prompt_label,
    )
