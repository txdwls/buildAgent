"""Unit tests for lazy Playwright lifecycle management."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import pytest
from playwright import async_api

from buildagent.tools.browser import session


class _FakePage:
    def __init__(self) -> None:
        self.timeouts: list[int] = []

    def set_default_navigation_timeout(self, timeout: int) -> None:
        self.timeouts.append(timeout)


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.closed = False

    async def new_context(self) -> _FakeContext:
        return self.context

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.launch_args: list[bool] = []

    async def launch(self, *, headless: bool) -> _FakeBrowser:
        self.launch_args.append(headless)
        return self.browser


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakeStarter:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self.playwright = playwright
        self.starts = 0

    async def start(self) -> _FakePlaywright:
        self.starts += 1
        return self.playwright


@pytest.mark.asyncio
async def test_get_page_initializes_once_and_shutdown_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await session.shutdown()
    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser)
    playwright = _FakePlaywright(chromium)
    starter = _FakeStarter(playwright)
    monkeypatch.setattr(async_api, "async_playwright", lambda: starter)

    try:
        first = await session.get_page(headless=False, nav_timeout_s=2.5)
        second = await session.get_page(headless=True, nav_timeout_s=9.0)

        assert first is page
        assert second is page
        assert starter.starts == 1
        assert chromium.launch_args == [False]
        assert page.timeouts == [2500]

        await session.shutdown()
        assert context.closed
        assert browser.closed
        assert playwright.stopped
        assert session._state.page is None
    finally:
        await session.shutdown()


def test_atexit_shutdown_returns_when_no_page() -> None:
    session._state.page = None
    session._atexit_shutdown()
