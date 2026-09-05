from __future__ import annotations

from typing import Any

import pytest

from buildagent.tools.browser import actions


class _FakePage:
    def __init__(self, url: str = "https://a.com/x") -> None:
        self.url = url
        self.click_calls: list[tuple[str, int]] = []
        self.fill_calls: list[tuple[str, str, int]] = []
        self.click_raises: Exception | None = None
        self.fill_raises: Exception | None = None

    async def click(self, selector: str, timeout: int) -> None:
        if self.click_raises is not None:
            raise self.click_raises
        self.click_calls.append((selector, timeout))

    async def fill(self, selector: str, value: str, timeout: int) -> None:
        if self.fill_raises is not None:
            raise self.fill_raises
        self.fill_calls.append((selector, value, timeout))


@pytest.fixture
def fake_page(monkeypatch: pytest.MonkeyPatch) -> _FakePage:
    page = _FakePage()

    async def _get_page(**_: Any) -> _FakePage:
        return page

    monkeypatch.setattr(actions, "get_page", _get_page)
    return page


def _tools(prefixes: str = "https://a.com/") -> dict[str, Any]:
    built = actions.build_browser_tools(
        allowed_url_prefixes=prefixes, headless=True, nav_timeout_s=5.0
    )
    return {tool.name: tool for tool in built}


@pytest.mark.asyncio
async def test_click_invokes_page_click_with_timeout(fake_page: _FakePage) -> None:
    tools = _tools()
    result = await tools["browser_click"].handler({"selector": "#go", "timeout_s": 2})
    assert result.startswith("ok: clicked #go")
    assert fake_page.click_calls == [("#go", 2000)]


@pytest.mark.asyncio
async def test_click_rejects_when_page_url_outside_allowlist(fake_page: _FakePage) -> None:
    fake_page.url = "https://evil.com/"
    tools = _tools()
    result = await tools["browser_click"].handler({"selector": "#go"})
    assert result.startswith("error: current page not in allowlist")
    assert fake_page.click_calls == []


@pytest.mark.asyncio
async def test_click_returns_error_string_on_failure(fake_page: _FakePage) -> None:
    fake_page.click_raises = RuntimeError("timeout")
    tools = _tools()
    result = await tools["browser_click"].handler({"selector": "#go"})
    assert result == "error: click failed: timeout"


@pytest.mark.asyncio
async def test_type_fills_selector_with_text(fake_page: _FakePage) -> None:
    tools = _tools()
    result = await tools["browser_type"].handler({"selector": "input[name=q]", "text": "hello"})
    assert result == "ok: filled input[name=q] (5 chars)"
    assert fake_page.fill_calls == [("input[name=q]", "hello", 10000)]


@pytest.mark.asyncio
async def test_type_rejects_when_page_url_outside_allowlist(fake_page: _FakePage) -> None:
    fake_page.url = "https://evil.com/"
    tools = _tools()
    result = await tools["browser_type"].handler({"selector": "#q", "text": "x"})
    assert result.startswith("error: current page not in allowlist")
    assert fake_page.fill_calls == []
