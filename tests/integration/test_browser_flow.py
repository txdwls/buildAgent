"""Real Playwright flow against a deterministic local HTML server."""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from buildagent.tools.browser import session
from buildagent.tools.browser.actions import build_browser_tools


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture
def local_site(tmp_path: Path) -> Iterator[str]:
    (tmp_path / "index.html").write_text(
        """<!doctype html>
<title>BuildAgent browser test</title>
<input id="name" aria-label="Name">
<button id="go" onclick="document.querySelector('#result').textContent = 'clicked'">Go</button>
<p id="result">ready</p>
""",
        encoding="utf-8",
    )
    handler = partial(_QuietHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_tools_complete_real_local_flow(local_site: str) -> None:
    await session.shutdown()
    try:
        try:
            page = await session.get_page(headless=True, nav_timeout_s=5.0)
        except Exception as exc:
            if "executable doesn't exist" in str(exc).lower():
                pytest.skip("Playwright Chromium is not installed")
            raise

        tools = {
            tool.name: tool
            for tool in build_browser_tools(
                allowed_url_prefixes=f"{local_site}/",
                headless=True,
                nav_timeout_s=5.0,
            )
        }
        url = f"{local_site}/index.html"

        opened = await tools["browser_open"].handler({"url": url})
        typed = await tools["browser_type"].handler(
            {"selector": "#name", "text": "Sungjin"}
        )
        clicked = await tools["browser_click"].handler({"selector": "#go"})
        blocked = await tools["browser_open"].handler({"url": "https://example.com/"})

        assert "status=200" in opened
        assert "BuildAgent browser test" in opened
        assert typed == "ok: filled #name (7 chars)"
        assert clicked.startswith("ok: clicked #go")
        assert blocked == "error: url not in allowlist: https://example.com/"
        assert await page.locator("#name").input_value() == "Sungjin"
        assert await page.locator("#result").inner_text() == "clicked"
    finally:
        await session.shutdown()
