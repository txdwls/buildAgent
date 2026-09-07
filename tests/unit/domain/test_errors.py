"""Domain error payload and message checks."""

from __future__ import annotations

from buildagent.domain import LoopBudgetExceeded, ToolNotFound
from buildagent.domain.errors import GuardrailBlocked


def test_tool_not_found_keeps_name() -> None:
    error = ToolNotFound("missing")
    assert error.name == "missing"
    assert str(error) == "tool not registered: missing"


def test_guardrail_blocked_keeps_layer_and_reason() -> None:
    error = GuardrailBlocked("input", "unsafe")
    assert error.layer == "input"
    assert error.reason == "unsafe"
    assert str(error) == "guardrail[input] blocked: unsafe"


def test_loop_budget_exceeded_keeps_iteration_count() -> None:
    error = LoopBudgetExceeded(3)
    assert error.iterations == 3
    assert str(error) == "loop exceeded max_iterations=3"
