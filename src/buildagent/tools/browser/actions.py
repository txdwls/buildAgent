"""Browser tools exposed to the agent.

Slice 1: browser_open only. Navigates the shared page to a URL and returns
a short summary (page title + visible text preview) the LLM can quote back.
Additional atomic tools (click, type, extract, screenshot) will be added in
later slices so each shows up as its own Langfuse span.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

from typing import Any

from buildagent.domain import Tool
from buildagent.tools.browser.allowlist import is_allowed, parse_allowlist
from buildagent.tools.browser.session import get_page

MAX_TEXT_PREVIEW = 2000


def build_browser_tools(
    *,
    allowed_url_prefixes: str,
    headless: bool,
    nav_timeout_s: float,
) -> list[Tool]:
    allowlist = parse_allowlist(allowed_url_prefixes)

    async def open_handler(arguments: dict[str, Any]) -> str:
        url: str = arguments["url"]
        if not is_allowed(url, allowlist):
            return f"error: url not in allowlist: {url}"
        page = await get_page(headless=headless, nav_timeout_s=nav_timeout_s)
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            return f"error: navigation failed: {exc}"
        status = response.status if response is not None else 0
        title = await page.title()
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        preview = text[:MAX_TEXT_PREVIEW]
        return f"status={status}\ntitle={title}\ntext_preview:\n{preview}"

    return [
        Tool(
            name="browser_open",
            description=(
                "Navigate the shared headless browser to a URL and return the page "
                "title plus a short visible-text preview. Use for JS-rendered pages "
                "or content behind interactions that http_fetch cannot reach."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Absolute URL to open. Must match one of the configured "
                            "URL prefixes when the allowlist is non-empty."
                        ),
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=open_handler,
        ),
    ]
