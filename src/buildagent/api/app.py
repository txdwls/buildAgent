"""FastAPI application factory.

Mounts /health plus the OpenAI-compatible surface (/v1/models,
/v1/chat/completions). The OpenAI client, tool registry, and Langfuse
prompt fetcher are wired in via `api/dependencies.py` (`Depends(...)`).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from buildagent.api.routes import health
from buildagent.api.routes.openai_compat import chat_router, models_router
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
    app.include_router(models_router)
    app.include_router(chat_router)
    return app


app = create_app()
