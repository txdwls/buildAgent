"""Opt-in health check for the local Langfuse service."""

from __future__ import annotations

import os

import httpx
import pytest

from buildagent.config import Settings


@pytest.mark.integration
def test_local_langfuse_health() -> None:
    if os.getenv("BUILDAGENT_RUN_LIVE_TESTS") != "1":
        pytest.skip("set BUILDAGENT_RUN_LIVE_TESTS=1 to contact Langfuse")

    settings = Settings()  # type: ignore[call-arg]
    response = httpx.get(
        f"{settings.langfuse_host.rstrip('/')}/api/public/health",
        timeout=5.0,
    )

    assert response.status_code == 200
