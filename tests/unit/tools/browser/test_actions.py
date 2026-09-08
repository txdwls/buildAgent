# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from buildagent.tools.browser import actions


class _FakeResponse:
    status = 200


class _FakePage:
    def __init__(self, url: str = "https://a.com/x") -> None:
        self.url = url
        self.click_calls: list[tuple[str, int]] = []
        self.fill_calls: list[tuple[str, str, int]] = []
        self.click_raises: Exception | None = None
        self.fill_raises: Exception | None = None
        self.goto_raises: Exception | None = None
        self.goto_calls: list[tuple[str, str]] = []
        self.title_value = "Test page"
        self.body_text = "Visible text"
        self.extract_values: list[str] = []
        self.extract_raises: Exception | None = None
        self.extract_calls: list[tuple[str, str, str]] = []
        self.screenshot_raises: Exception | None = None
        self.screenshot_calls: list[tuple[str, bool]] = []
        self.screenshot_bytes = b"\x89PNG-fake"

    async def goto(self, url: str, wait_until: str) -> _FakeResponse:
        if self.goto_raises is not None:
            raise self.goto_raises
        self.goto_calls.append((url, wait_until))
        self.url = url
        return _FakeResponse()

    async def title(self) -> str:
        return self.title_value

    async def evaluate(self, _: str) -> str:
        return self.body_text

    async def click(self, selector: str, timeout: int) -> None:
        if self.click_raises is not None:
            raise self.click_raises
        self.click_calls.append((selector, timeout))

    async def fill(self, selector: str, value: str, timeout: int) -> None:
        if self.fill_raises is not None:
            raise self.fill_raises
        self.fill_calls.append((selector, value, timeout))

    async def eval_on_selector_all(
        self, selector: str, script: str, arg: str
    ) -> list[str]:
        if self.extract_raises is not None:
            raise self.extract_raises
        self.extract_calls.append((selector, script, arg))
        return list(self.extract_values)

    async def screenshot(self, *, path: str, full_page: bool) -> None:
        if self.screenshot_raises is not None:
            raise self.screenshot_raises
        self.screenshot_calls.append((path, full_page))
        Path(path).write_bytes(self.screenshot_bytes)


@pytest.fixture
def fake_page(monkeypatch: pytest.MonkeyPatch) -> _FakePage:
    page = _FakePage()

    async def _get_page(**_: Any) -> _FakePage:
        return page

    monkeypatch.setattr(actions, "get_page", _get_page)
    return page


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _tools(
    workspace: Path, prefixes: str = "https://a.com/"
) -> dict[str, Any]:
    built = actions.build_browser_tools(
        allowed_url_prefixes=prefixes,
        headless=True,
        nav_timeout_s=5.0,
        filesystem_root=workspace,
    )
    return {tool.name: tool for tool in built}


@pytest.mark.asyncio
async def test_open_returns_status_title_and_text_preview(
    fake_page: _FakePage, workspace: Path
) -> None:
    tools = _tools(workspace)

    result = await tools["browser_open"].handler({"url": "https://a.com/new"})

    assert result == "status=200\ntitle=Test page\ntext_preview:\nVisible text"
    assert fake_page.goto_calls == [("https://a.com/new", "domcontentloaded")]


@pytest.mark.asyncio
async def test_open_rejects_url_outside_allowlist(
    fake_page: _FakePage, workspace: Path
) -> None:
    result = await _tools(workspace)["browser_open"].handler(
        {"url": "https://evil.com/"}
    )

    assert result == "error: url not in allowlist: https://evil.com/"
    assert fake_page.goto_calls == []


@pytest.mark.asyncio
async def test_open_returns_navigation_error(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.goto_raises = RuntimeError("timeout")

    result = await _tools(workspace)["browser_open"].handler(
        {"url": "https://a.com/new"}
    )

    assert result == "error: navigation failed: timeout"


@pytest.mark.asyncio
async def test_click_invokes_page_click_with_timeout(
    fake_page: _FakePage, workspace: Path
) -> None:
    tools = _tools(workspace)
    result = await tools["browser_click"].handler({"selector": "#go", "timeout_s": 2})
    assert result.startswith("ok: clicked #go")
    assert fake_page.click_calls == [("#go", 2000)]


@pytest.mark.asyncio
async def test_click_rejects_when_page_url_outside_allowlist(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.url = "https://evil.com/"
    tools = _tools(workspace)
    result = await tools["browser_click"].handler({"selector": "#go"})
    assert result.startswith("error: current page not in allowlist")
    assert fake_page.click_calls == []


@pytest.mark.asyncio
async def test_click_returns_error_string_on_failure(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.click_raises = RuntimeError("timeout")
    tools = _tools(workspace)
    result = await tools["browser_click"].handler({"selector": "#go"})
    assert result == "error: click failed: timeout"


@pytest.mark.asyncio
async def test_type_fills_selector_with_text(
    fake_page: _FakePage, workspace: Path
) -> None:
    tools = _tools(workspace)
    result = await tools["browser_type"].handler(
        {"selector": "input[name=q]", "text": "hello"}
    )
    assert result == "ok: filled input[name=q] (5 chars)"
    assert fake_page.fill_calls == [("input[name=q]", "hello", 10000)]


@pytest.mark.asyncio
async def test_type_rejects_when_page_url_outside_allowlist(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.url = "https://evil.com/"
    tools = _tools(workspace)
    result = await tools["browser_type"].handler({"selector": "#q", "text": "x"})
    assert result.startswith("error: current page not in allowlist")
    assert fake_page.fill_calls == []


@pytest.mark.asyncio
async def test_type_returns_error_string_on_failure(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.fill_raises = RuntimeError("timeout")

    result = await _tools(workspace)["browser_type"].handler(
        {"selector": "#q", "text": "x"}
    )

    assert result == "error: type failed: timeout"


@pytest.mark.asyncio
async def test_extract_returns_inner_text_when_attr_omitted(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.extract_values = ["First link", "Second\n link  "]

    result = await _tools(workspace)["browser_extract"].handler(
        {"selector": "a"}
    )

    assert result == "matches=2 (returned 2)\nFirst link\nSecond link"
    assert fake_page.extract_calls == [("a", actions._EXTRACT_SCRIPT, "")]


@pytest.mark.asyncio
async def test_extract_returns_attribute_values(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.extract_values = ["/x", "/y", "/z"]

    result = await _tools(workspace)["browser_extract"].handler(
        {"selector": "a", "attr": "href", "limit": 2}
    )

    assert result == "matches=3 (returned 2)\n/x\n/y"
    assert fake_page.extract_calls == [("a", actions._EXTRACT_SCRIPT, "href")]


@pytest.mark.asyncio
async def test_extract_reports_zero_matches(
    fake_page: _FakePage, workspace: Path
) -> None:
    result = await _tools(workspace)["browser_extract"].handler(
        {"selector": ".missing"}
    )

    assert result == "matches=0 for .missing"


@pytest.mark.asyncio
async def test_extract_rejects_when_page_url_outside_allowlist(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.url = "https://evil.com/"

    result = await _tools(workspace)["browser_extract"].handler({"selector": "a"})

    assert result.startswith("error: current page not in allowlist")
    assert fake_page.extract_calls == []


@pytest.mark.asyncio
async def test_extract_returns_error_string_on_failure(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.extract_raises = RuntimeError("selector broken")

    result = await _tools(workspace)["browser_extract"].handler({"selector": "a"})

    assert result == "error: extract failed: selector broken"


@pytest.mark.asyncio
async def test_screenshot_writes_png_under_workspace(
    fake_page: _FakePage, workspace: Path
) -> None:
    result = await _tools(workspace)["browser_screenshot"].handler(
        {"path": "shots/home.png", "full_page": True}
    )

    written = workspace / "shots" / "home.png"
    assert written.is_file()
    assert written.read_bytes() == fake_page.screenshot_bytes
    assert fake_page.screenshot_calls == [(str(written), True)]
    assert result == (
        f"ok: wrote screenshot to shots/home.png "
        f"({len(fake_page.screenshot_bytes)} bytes, full_page=True)"
    )


@pytest.mark.asyncio
async def test_screenshot_rejects_when_page_url_outside_allowlist(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.url = "https://evil.com/"

    result = await _tools(workspace)["browser_screenshot"].handler(
        {"path": "shot.png"}
    )

    assert result.startswith("error: current page not in allowlist")
    assert fake_page.screenshot_calls == []
    assert not (workspace / "shot.png").exists()


@pytest.mark.asyncio
async def test_screenshot_rejects_path_that_escapes_workspace(
    fake_page: _FakePage, workspace: Path
) -> None:
    result = await _tools(workspace)["browser_screenshot"].handler(
        {"path": "../outside.png"}
    )

    assert result.startswith("error: path escapes workspace root")
    assert fake_page.screenshot_calls == []


@pytest.mark.asyncio
async def test_screenshot_returns_error_string_on_failure(
    fake_page: _FakePage, workspace: Path
) -> None:
    fake_page.screenshot_raises = RuntimeError("gpu missing")

    result = await _tools(workspace)["browser_screenshot"].handler(
        {"path": "shot.png"}
    )

    assert result == "error: screenshot failed: gpu missing"
