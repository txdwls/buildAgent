"""CLI orchestration tests with the external client and tools replaced."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import runpy
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from buildagent.cli import main as cli
from buildagent.domain import Tool


def _settings() -> Any:
    return SimpleNamespace(
        tavily_api_key="tavily",
        tavily_max_results=2,
        filesystem_root="/tmp/workspace",
        openai_model="model",
        max_loop_iterations=3,
        system_prompt_name="main_agent",
        system_prompt_label="production",
    )


def _tool(name: str) -> Tool:
    async def handler(_: dict[str, Any]) -> str:
        return name

    return Tool(name=name, description=name, parameters={}, handler=handler)


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]) -> None:
    settings = _settings()

    def get_settings() -> Any:
        return settings

    def init_langfuse(_: Any) -> None:
        return None

    def build_client(_: Any) -> Any:
        return "client"

    def build_web(*_: Any) -> Tool:
        return _tool("web_search")

    def build_filesystem(_: Any) -> list[Tool]:
        return [_tool("fs_read")]

    def get_prompt(*_: Any) -> str:
        return "system prompt"

    monkeypatch.setattr(cli, "get_settings", get_settings)
    monkeypatch.setattr(cli, "init_langfuse", init_langfuse)
    monkeypatch.setattr(cli, "build_openai_client", build_client)
    monkeypatch.setattr(cli, "build_web_search_tool", build_web)
    monkeypatch.setattr(cli, "build_filesystem_tools", build_filesystem)
    monkeypatch.setattr(cli, "get_prompt_text", get_prompt)

    async def run_loop(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "answer"

    monkeypatch.setattr(cli, "run_loop", run_loop)


@pytest.mark.asyncio
async def test_single_builds_runtime_and_prints_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    _patch_runtime(monkeypatch, calls)

    await cli._single("question")

    assert capsys.readouterr().out == "answer\n"
    assert calls[0]["model"] == "model"
    assert calls[0]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "question"},
    ]


@pytest.mark.asyncio
async def test_chat_handles_one_turn_then_eof(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    _patch_runtime(monkeypatch, calls)
    inputs = iter(["question"])

    def read_input(_: str) -> str:
        try:
            return next(inputs)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", read_input)

    await cli._chat()

    output = capsys.readouterr().out
    assert "buildAgent MVP" in output
    assert "agent> answer" in output
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_chat_exits_on_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _patch_runtime(monkeypatch, calls)
    def empty_input(_: str) -> str:
        return ""

    monkeypatch.setattr("builtins.input", empty_input)

    await cli._chat()

    assert calls == []


@pytest.mark.parametrize(
    ("argv", "expected"),
    [(["buildagent", "--single", "question"], "single"), (["buildagent"], "chat")],
)
def test_main_dispatches_and_flushes(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: str
) -> None:
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(sys, "argv", argv)

    async def single(query: str) -> None:
        calls.append(("single", query))

    async def chat() -> None:
        calls.append(("chat", None))

    class _Langfuse:
        def __init__(self) -> None:
            self.flushes = 0

        def flush(self) -> None:
            self.flushes += 1

    langfuse = _Langfuse()
    monkeypatch.setattr(cli, "_single", single)
    monkeypatch.setattr(cli, "_chat", chat)
    monkeypatch.setattr(cli, "get_client", lambda: langfuse)

    cli.main()

    assert calls[0][0] == expected
    assert langfuse.flushes == 1


def test_module_entrypoint_calls_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_main() -> None:
        calls.append("called")

    monkeypatch.setattr(cli, "main", fake_main)

    runpy.run_module("buildagent.__main__", run_name="__main__")

    assert calls == ["called"]
