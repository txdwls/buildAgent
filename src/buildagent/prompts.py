"""Langfuse-backed prompt fetcher.

All system prompts, judge rubrics, and tool description templates live in
Langfuse prompt management (versioned in the UI). This module is the only
place the app fetches them. Fallback text is returned when Langfuse is
unreachable so local smoke tests do not require a fully-seeded Langfuse.
"""

from __future__ import annotations

from functools import lru_cache

from langfuse import get_client

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful research assistant with access to a web_search tool.\n"
    "Guidelines:\n"
    "- Use web_search for current events, facts, or anything beyond your knowledge cutoff.\n"
    "- After searching, synthesize the results in your own words. Cite source URLs when useful.\n"
    "- Be concise. Do not restate the user's question."
)


@lru_cache(maxsize=32)
def get_prompt_text(name: str, label: str = "production") -> str:
    """Return the current prompt body from Langfuse, or a hardcoded fallback.

    Cached for the process lifetime; restart to pick up new versions.
    """

    try:
        lf = get_client()
        prompt = lf.get_prompt(name, label=label)
        return prompt.prompt  # type: ignore[no-any-return]
    except Exception:
        if name == "main_agent":
            return DEFAULT_SYSTEM_PROMPT
        raise
