"""Interactive multi-turn REPL for the Phase 1 MVP.

Usage:
    uv run python -m buildagent
    (or `python -m buildagent` inside a synced venv)
"""

from __future__ import annotations

import argparse
import asyncio

from buildagent.agent import run_loop
from buildagent.config import get_settings
from buildagent.domain import Message, system_message, user_message
from buildagent.llm import build_openai_client
from buildagent.observability import init_langfuse
from buildagent.prompts import get_prompt_text
from buildagent.tools import ToolRegistry, build_web_search_tool


async def _chat() -> None:
    settings = get_settings()
    init_langfuse(settings)
    client = build_openai_client(settings)

    tools = ToolRegistry()
    tools.register(
        build_web_search_tool(settings.tavily_api_key, settings.tavily_max_results)
    )

    system_text = get_prompt_text(settings.system_prompt_name, settings.system_prompt_label)
    history: list[Message] = [system_message(system_text)]

    print("buildAgent MVP. Type your question. Empty line or Ctrl-D to exit.")
    while True:
        try:
            user_input = input("you> ").strip()
        except EOFError:
            print()
            return
        if not user_input:
            return
        history.append(user_message(user_input))
        answer = await run_loop(
            client=client,
            model=settings.openai_model,
            messages=history,
            tools=tools,
            max_iterations=settings.max_loop_iterations,
        )
        history.append({"role": "assistant", "content": answer})
        print(f"agent> {answer}\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="buildagent", description="buildAgent CLI")
    parser.add_argument(
        "--single",
        metavar="QUERY",
        help="Run a single query and exit instead of the interactive REPL.",
    )
    args = parser.parse_args()

    if args.single:
        asyncio.run(_single(args.single))
    else:
        asyncio.run(_chat())


async def _single(query: str) -> None:
    settings = get_settings()
    init_langfuse(settings)
    client = build_openai_client(settings)
    tools = ToolRegistry()
    tools.register(
        build_web_search_tool(settings.tavily_api_key, settings.tavily_max_results)
    )
    system_text = get_prompt_text(settings.system_prompt_name, settings.system_prompt_label)
    messages: list[Message] = [system_message(system_text), user_message(query)]
    answer = await run_loop(
        client=client,
        model=settings.openai_model,
        messages=messages,
        tools=tools,
        max_iterations=settings.max_loop_iterations,
    )
    print(answer)


if __name__ == "__main__":
    main()
