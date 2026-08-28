"""Tavily web search tool.

Calls Tavily's /search endpoint via httpx and formats the top results
as a plain-text block the LLM can quote back. We keep the schema
minimal on purpose: fewer knobs mean fewer bad calls from the model.
"""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
from __future__ import annotations

from typing import Any

import httpx

from buildagent.domain import Tool

TAVILY_ENDPOINT = "https://api.tavily.com/search"

WEB_SEARCH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Search query. Prefer natural-language questions over keyword-only queries."
            ),
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


def build_web_search_tool(api_key: str, max_results: int = 5) -> Tool:
    async def handler(arguments: dict[str, Any]) -> str:
        query = arguments["query"]
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": True,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(TAVILY_ENDPOINT, json=payload)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        return _format_results(query, data)

    return Tool(
        name="web_search",
        description=(
            "Search the public web for current information. Use when the user asks "
            "about recent events, facts likely to change over time, or topics beyond "
            "the model's training cutoff."
        ),
        parameters=WEB_SEARCH_PARAMETERS,
        handler=handler,
    )


def _format_results(query: str, data: dict[str, Any]) -> str:
    lines: list[str] = [f"Query: {query}"]
    answer = data.get("answer")
    if answer:
        lines.append(f"Summary: {answer}")
    results = data.get("results") or []
    if not results:
        lines.append("No results.")
        return "\n".join(lines)
    lines.append("Results:")
    for i, result in enumerate(results, 1):
        title = result.get("title", "")
        url = result.get("url", "")
        content = (result.get("content") or "").strip().replace("\n", " ")
        lines.append(f"{i}. {title} ({url})\n   {content}")
    return "\n".join(lines)
