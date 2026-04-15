from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WorkflowExecutionContext:
    """Execution-scoped context shared with workflow tools."""

    run_id: str | None = None
    approval_handler: Any = None


_WORKFLOW_EXECUTION_CONTEXT: ContextVar[WorkflowExecutionContext | None] = ContextVar(
    "workflow_execution_context",
    default=None,
)


def get_workflow_execution_context() -> WorkflowExecutionContext | None:
    """Return the current workflow execution context, if one is active."""

    return _WORKFLOW_EXECUTION_CONTEXT.get()


def set_workflow_execution_context(
    context: WorkflowExecutionContext | None,
) -> Token[WorkflowExecutionContext | None]:
    """Set the current workflow execution context."""

    return _WORKFLOW_EXECUTION_CONTEXT.set(context)


def reset_workflow_execution_context(
    token: Token[WorkflowExecutionContext | None],
) -> None:
    """Restore the previous workflow execution context."""

    _WORKFLOW_EXECUTION_CONTEXT.reset(token)
