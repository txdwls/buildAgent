"""FastAPI application factory.

Phase 1 exposes only /health. The OpenAI-compatible /v1/chat/completions
endpoint lands in Phase 2.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from buildagent.api.routes import health
from buildagent.config import get_settings
from buildagent.observability import init_langfuse


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    init_langfuse(settings)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="buildAgent", lifespan=_lifespan)
    app.include_router(health.router)
    return app


app = create_app()
