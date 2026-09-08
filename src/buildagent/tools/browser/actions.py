"""Browser tools exposed to the agent.

browser_open navigates the shared page. browser_click and browser_type
interact with the current page via CSS selector. browser_extract reads
text or an attribute from matching elements. browser_screenshot writes
a PNG into the filesystem root-jail. Each atomic tool shows up as its
own Langfuse span.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

from pathlib import Path
from typing import Any

from buildagent.domain import Tool
from buildagent.tools.browser.allowlist import is_allowed, parse_allowlist
from buildagent.tools.browser.session import get_page
from buildagent.tools.filesystem import resolve_under_root

MAX_TEXT_PREVIEW = 2000
DEFAULT_ACTION_TIMEOUT_S = 10.0
DEFAULT_EXTRACT_LIMIT = 20
MAX_EXTRACT_CHARS = 4000

_EXTRACT_SCRIPT = (
    "(els, attr) => els.map(el => "
    "attr ? (el.getAttribute(attr) || '') : (el.innerText || ''))"
)


def build_browser_tools(
    *,
    allowed_url_prefixes: str,
    headless: bool,
    nav_timeout_s: float,
    filesystem_root: str | Path,
) -> list[Tool]:
    allowlist = parse_allowlist(allowed_url_prefixes)
    root_path = Path(filesystem_root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)

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

    async def extract_handler(arguments: dict[str, Any]) -> str:
        selector: str = arguments["selector"]
        attr: str = arguments.get("attr", "") or ""
        limit = int(arguments.get("limit", DEFAULT_EXTRACT_LIMIT))
        page = await get_page(headless=headless, nav_timeout_s=nav_timeout_s)
        if not is_allowed(page.url, allowlist):
            return f"error: current page not in allowlist: {page.url}"
        try:
            values = await page.eval_on_selector_all(selector, _EXTRACT_SCRIPT, attr)
        except Exception as exc:
            return f"error: extract failed: {exc}"
        if not values:
            return f"matches=0 for {selector}"
        clipped = [_one_line(str(v)) for v in values[:limit]]
        body = "\n".join(clipped)[:MAX_EXTRACT_CHARS]
        return f"matches={len(values)} (returned {len(clipped)})\n{body}"

    async def screenshot_handler(arguments: dict[str, Any]) -> str:
        rel: str = arguments["path"]
        full_page = bool(arguments.get("full_page", False))
        page = await get_page(headless=headless, nav_timeout_s=nav_timeout_s)
        if not is_allowed(page.url, allowlist):
            return f"error: current page not in allowlist: {page.url}"
        target, err = resolve_under_root(root_path, rel)
        if err is not None:
            return err
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(target), full_page=full_page)
        except Exception as exc:
            return f"error: screenshot failed: {exc}"
        size = target.stat().st_size
        return f"ok: wrote screenshot to {rel} ({size} bytes, full_page={full_page})"

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
        Tool(
            name="browser_extract",
            description=(
                "Extract visible text (default) or a named attribute from every "
                "element on the current page matching a CSS selector. Returns one "
                "value per line, capped at the configured limit and total character "
                "budget. Call browser_open first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for the elements to read.",
                    },
                    "attr": {
                        "type": "string",
                        "description": (
                            "Optional attribute name (e.g. 'href'). Omit to read "
                            "visible innerText of each match."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of matches to return. "
                            f"Defaults to {DEFAULT_EXTRACT_LIMIT}."
                        ),
                    },
                },
                "required": ["selector"],
                "additionalProperties": False,
            },
            handler=extract_handler,
        ),
        Tool(
            name="browser_screenshot",
            description=(
                "Capture a PNG of the current browser page and save it inside the "
                "agent workspace. The path is resolved under the same root-jail as "
                "fs_write. Call browser_open first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Workspace-relative destination path for the PNG "
                            "(e.g. 'screens/home.png')."
                        ),
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": (
                            "If true, capture the entire scroll height. Defaults "
                            "to the visible viewport."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=screenshot_handler,
        ),
    ]


def _one_line(value: str) -> str:
    return " ".join(value.split())
