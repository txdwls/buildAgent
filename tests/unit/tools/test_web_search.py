"""Deterministic tests for Tavily payloads and result formatting."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from buildagent.tools import web_search

# pyright: reportPrivateUsage=false


def test_format_results_includes_summary_and_normalizes_content() -> None:
    result = web_search._format_results(
        "python",
        {
            "answer": "A short answer",
            "results": [
                {"title": "Docs", "url": "https://example.com", "content": "one\ntwo"}
            ],
        },
    )

    assert "Query: python" in result
    assert "Summary: A short answer" in result
    assert "1. Docs (https://example.com)\n   one two" in result


def test_format_results_reports_empty_results() -> None:
    assert web_search._format_results("nothing", {"results": []}) == (
        "Query: nothing\nNo results."
    )


@pytest.mark.asyncio
async def test_handler_posts_expected_tavily_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"answer": "ok", "results": []})

    real_client = httpx.AsyncClient

    def build_client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", build_client)
    tool = web_search.build_web_search_tool("test-key", max_results=2)

    result = await tool.handler({"query": "latest python"})

    assert result == "Query: latest python\nSummary: ok\nNo results."
    assert len(requests) == 1
    assert str(requests[0].url) == web_search.TAVILY_ENDPOINT
    assert json.loads(requests[0].content) == {
        "api_key": "test-key",
        "query": "latest python",
        "search_depth": "basic",
        "max_results": 2,
        "include_answer": True,
    }


@pytest.mark.asyncio
async def test_handler_propagates_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    real_client = httpx.AsyncClient

    def build_client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", build_client)
    tool = web_search.build_web_search_tool("test-key")

    with pytest.raises(httpx.HTTPStatusError):
        await tool.handler({"query": "down"})
