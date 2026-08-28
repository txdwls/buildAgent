"""OpenAI async client factory, wrapped with Langfuse auto-instrumentation.

Importing `from langfuse.openai import AsyncOpenAI` returns a subclass that
records every request/response as a Langfuse `generation`, capturing model,
input tokens, output tokens, and latency without any manual span code.
This is the only place the OpenAI SDK is imported in the app; other layers
receive the built client via DI.
"""

from __future__ import annotations

from langfuse.openai import AsyncOpenAI  # pyright: ignore[reportPrivateImportUsage]

from buildagent.config import Settings


def build_openai_client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_request_timeout_s,
    )
