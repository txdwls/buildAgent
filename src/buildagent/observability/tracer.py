"""Langfuse initialization helpers.

Langfuse v4 auto-instruments OpenAI calls once its client is initialized
with credentials (either via env vars LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY
/ LANGFUSE_SECRET_KEY, or explicit args). We call `init_langfuse()`
during app/CLI startup so the env-based bootstrap runs before any LLM
call and any `@observe`-decorated function sees a live client.
"""

from __future__ import annotations

import os

from langfuse import Langfuse, get_client

from buildagent.config import Settings


def init_langfuse(settings: Settings) -> Langfuse:
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", settings.langfuse_tracing_environment)
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    return get_client()


def trace_task(source: str, question: object) -> str:
    """Classify only the default Open WebUI background prompts for display."""
    # ponytail: prompt-prefix heuristic; use an explicit task header if WebUI
    # exposes one or custom prompts make these defaults unreliable.
    if source == "openwebui" and isinstance(question, str):
        for prefix, task in (
            ("Generate a concise title summarizing the chat history.", "title"),
            ("Suggest 3-5 relevant follow-up questions or prompts", "followup"),
            ("Generate 1-3 broad tags categorizing the main themes", "tags"),
        ):
            if question.startswith(f"### Task:\n{prefix}"):
                return task
    return "chat"
