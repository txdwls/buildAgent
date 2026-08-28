"""Seed Langfuse with the Phase 1 system prompt.

Run once (or after editing DEFAULT_SYSTEM_PROMPT) to register the
'main_agent' prompt at label='production'. Subsequent edits should be
done in the Langfuse UI so version history and A/B experiments work.

    uv run --env-file .env python scripts/seed_prompts.py
"""

from __future__ import annotations

from langfuse import get_client

from buildagent.prompts import DEFAULT_SYSTEM_PROMPT


def main() -> None:
    lf = get_client()
    prompt = lf.create_prompt(
        name="main_agent",
        prompt=DEFAULT_SYSTEM_PROMPT,
        labels=["production"],
        type="text",
    )
    print(f"seeded prompt 'main_agent' version={prompt.version} label=production")


if __name__ == "__main__":
    main()
