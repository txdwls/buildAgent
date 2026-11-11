"""Interactive multi-turn REPL for the Phase 1 MVP.

Usage:
    uv run python -m buildagent
    (or `python -m buildagent` inside a synced venv)
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from langfuse import get_client

from buildagent.agent import run_loop
from buildagent.config import get_settings
from buildagent.domain import GuardrailBlocked, Message, system_message, user_message
from buildagent.llm import build_openai_client
from buildagent.observability import init_langfuse
from buildagent.prompts import get_prompt_text
from buildagent.tools import (
    ToolRegistry,
    build_filesystem_tools,
    build_web_search_tool,
)

_CLI_ERRORS = {
    "context_input": "error: the conversation has an invalid message structure.",
    "context": "error: the request does not fit the context budget.",
    "generation": "error: the model response ended before it was complete.",
}


def _error_line(exc: GuardrailBlocked) -> str:
    return _CLI_ERRORS.get(exc.layer, "error: the request could not be completed.")


async def _chat() -> None:
    settings = get_settings()
    init_langfuse(settings)
    client = build_openai_client(settings)

    tools = ToolRegistry()
    tools.register(build_web_search_tool(settings.tavily_api_key, settings.tavily_max_results))
    for tool in build_filesystem_tools(settings.filesystem_root):
        tools.register(tool)

    system_text = get_prompt_text(settings.system_prompt_name, settings.system_prompt_label)
    history: list[Message] = [system_message(system_text)]
    session_id = f"cli-{uuid4().hex}"

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
        try:
            answer = await run_loop(
                client=client,
                model=settings.openai_model,
                messages=history,
                tools=tools,
                max_iterations=settings.max_loop_iterations,
                context_budget_tokens=settings.context_budget_tokens,
                session_id=session_id,
            )
        except GuardrailBlocked as exc:
            # Keep history sendable: drop the turn that could not be answered.
            history.pop()
            print(f"{_error_line(exc)}\n")
            continue
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

    try:
        if args.single:
            asyncio.run(_single(args.single))
        else:
            asyncio.run(_chat())
    finally:
        get_client().flush()


async def _single(query: str) -> None:
    settings = get_settings()
    init_langfuse(settings)
    client = build_openai_client(settings)
    tools = ToolRegistry()
    tools.register(build_web_search_tool(settings.tavily_api_key, settings.tavily_max_results))
    for tool in build_filesystem_tools(settings.filesystem_root):
        tools.register(tool)
    system_text = get_prompt_text(settings.system_prompt_name, settings.system_prompt_label)
    messages: list[Message] = [system_message(system_text), user_message(query)]
    try:
        answer = await run_loop(
            client=client,
            model=settings.openai_model,
            messages=messages,
            tools=tools,
            max_iterations=settings.max_loop_iterations,
            context_budget_tokens=settings.context_budget_tokens,
        )
    except GuardrailBlocked as exc:
        print(_error_line(exc))
        raise SystemExit(1) from exc
    print(answer)


if __name__ == "__main__":
    main()
