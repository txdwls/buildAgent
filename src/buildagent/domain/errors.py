class AgentError(Exception):
    """Base for all buildAgent domain errors."""


class ToolError(AgentError):
    """Raised when a tool fails during dispatch."""


class ToolNotFound(ToolError):  # noqa: N818
    """The LLM asked for a tool that is not registered."""

    def __init__(self, name: str) -> None:
        super().__init__(f"tool not registered: {name}")
        self.name = name


class LoopBudgetExceeded(AgentError):  # noqa: N818
    """The agent loop hit its max_iterations cap without terminating."""

    def __init__(self, iterations: int) -> None:
        super().__init__(f"loop exceeded max_iterations={iterations}")
        self.iterations = iterations


class GuardrailBlocked(AgentError):  # noqa: N818
    """A guardrail rejected an input, output, or tool execution."""

    def __init__(self, layer: str, reason: str) -> None:
        super().__init__(f"guardrail[{layer}] blocked: {reason}")
        self.layer = layer
        self.reason = reason
