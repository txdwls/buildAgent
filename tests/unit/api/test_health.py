from __future__ import annotations

import pytest

from buildagent.api.routes.health import health


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    assert await health() == {"status": "ok"}
