"""Browser tools exposed to the agent.

Slice 1: browser_open navigates the shared page.
Slice 2: browser_click and browser_type interact with the current page via
CSS selector. Each atomic tool shows up as its own Langfuse span.
Remaining slices (extract, screenshot) land later.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

from typing import Any

from buildagent.domain import Tool
from buildagent.tools.browser.allowlist import is_allowed, parse_allowlist
from buildagent.tools.browser.session import get_page

MAX_TEXT_PREVIEW = 2000
DEFAULT_ACTION_TIMEOUT_S = 10.0


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

    async def click_handler(arguments: dict[str, Any]) -> str:
        selector: str = arguments["selector"]
        timeout_s = float(arguments.get("timeout_s", DEFAULT_ACTION_TIMEOUT_S))
        page = await get_page(headless=headless, nav_timeout_s=nav_timeout_s)
        if not is_allowed(page.url, allowlist):
            return f"error: current page not in allowlist: {page.url}"
        try:
            await page.click(selector, timeout=int(timeout_s * 1000))
        except Exception as exc:
            return f"error: click failed: {exc}"
        return f"ok: clicked {selector}\nurl={page.url}"

    async def type_handler(arguments: dict[str, Any]) -> str:
        selector: str = arguments["selector"]
        text: str = arguments["text"]
        timeout_s = float(arguments.get("timeout_s", DEFAULT_ACTION_TIMEOUT_S))
        page = await get_page(headless=headless, nav_timeout_s=nav_timeout_s)
        if not is_allowed(page.url, allowlist):
            return f"error: current page not in allowlist: {page.url}"
        try:
            await page.fill(selector, text, timeout=int(timeout_s * 1000))
        except Exception as exc:
            return f"error: type failed: {exc}"
        return f"ok: filled {selector} ({len(text)} chars)"

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
        Tool(
            name="browser_click",
            description=(
                "Click an element on the current browser page identified by a CSS "
                "selector. Call browser_open first; the click runs on the page that "
                "browser_open loaded."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element to click.",
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": (
                            "Wait up to this many seconds for the element. "
                            f"Defaults to {DEFAULT_ACTION_TIMEOUT_S}."
                        ),
                    },
                },
                "required": ["selector"],
                "additionalProperties": False,
            },
            handler=click_handler,
        ),
        Tool(
            name="browser_type",
            description=(
                "Fill an input or textarea on the current browser page identified "
                "by a CSS selector, replacing any existing value with the given "
                "text. Call browser_open first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the input or textarea.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to fill into the element.",
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": (
                            "Wait up to this many seconds for the element. "
                            f"Defaults to {DEFAULT_ACTION_TIMEOUT_S}."
                        ),
                    },
                },
                "required": ["selector", "text"],
                "additionalProperties": False,
            },
            handler=type_handler,
        ),
    ]
