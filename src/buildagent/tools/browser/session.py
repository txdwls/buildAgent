"""Lazy shared Playwright session.

One browser + one context + one page shared across all browser tool calls
in a process. Playwright itself is imported lazily so unit tests that
don't touch the browser don't need the runtime dep installed.

ponytail: single global page, no per-conversation isolation. Upgrade to
per-session contexts when multi-conversation isolation matters.
"""

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

import asyncio
import atexit
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


@dataclass
class _State:
    playwright: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None


_state = _State()
_lock = asyncio.Lock()


async def get_page(*, headless: bool = True, nav_timeout_s: float = 30.0) -> Any:
    async with _lock:
        if _state.page is not None:
            return _state.page
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_navigation_timeout(int(nav_timeout_s * 1000))
        _state.playwright = pw
        _state.browser = browser
        _state.context = context
        _state.page = page
        return page


async def shutdown() -> None:
    async with _lock:
        if _state.context is not None:
            await _state.context.close()
        if _state.browser is not None:
            await _state.browser.close()
        if _state.playwright is not None:
            await _state.playwright.stop()
        _state.playwright = None
        _state.browser = None
        _state.context = None
        _state.page = None


def _atexit_shutdown() -> None:
    if _state.page is None:
        return
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(shutdown())
        loop.close()
    except Exception:
        pass


atexit.register(_atexit_shutdown)
