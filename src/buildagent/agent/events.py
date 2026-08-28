"""Streaming events emitted by the agent loop.

The loop yields these events so callers (SSE route, CLI, tests) can react to
tool progress and stream final-answer tokens without reimplementing the loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A token from the final assistant answer."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ToolCompleted:
    name: str
    result: str


@dataclass(frozen=True, slots=True)
class LoopCompleted:
    """Loop finished normally with a final assistant message (no tool_calls)."""


type LoopEvent = TextDelta | ToolStarted | ToolCompleted | LoopCompleted
