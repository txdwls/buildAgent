"""Opt-in smoke tests for real OpenAI and Tavily requests."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from buildagent.agent import run_loop
from buildagent.config import Settings
from buildagent.domain import user_message
from buildagent.llm import build_openai_client
from buildagent.observability import init_langfuse
from buildagent.tools import ToolRegistry, build_web_search_tool

pytestmark = pytest.mark.e2e


def _live_settings() -> Settings:
    if os.getenv("BUILDAGENT_RUN_LIVE_TESTS") != "1":
        pytest.skip("set BUILDAGENT_RUN_LIVE_TESTS=1 to contact external APIs")
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        pytest.skip(f"live test credentials are not configured: {exc}")


@pytest.mark.asyncio
async def test_tavily_search_reaches_real_api() -> None:
    settings = _live_settings()
    tool = build_web_search_tool(settings.tavily_api_key, max_results=1)

    result = await tool.handler({"query": "Python programming language"})

    assert result.startswith("Query: Python programming language")


@pytest.mark.asyncio
async def test_openai_loop_reaches_real_api() -> None:
    settings = _live_settings()
    init_langfuse(settings)
    client = build_openai_client(settings)
    try:
        answer = await run_loop(
            client=client,
            model=settings.openai_model,
            messages=[user_message("Reply with exactly OK.")],
            tools=ToolRegistry(),
            max_iterations=1,
            source="e2e",
        )
    finally:
        await client.close()

    assert answer.strip()
