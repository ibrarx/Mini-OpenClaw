"""
Execution manager — runs validated tools.

Invokes tools only after policy validation. Captures command
arguments, outputs, artifacts, timing, exit codes, and errors.
Every action becomes observable and auditable.

Full implementation in T03; this file provides the class interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..models.step import RunStep, ToolResult

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Raised when tool execution fails unexpectedly."""


class Executor:
    """Executes validated tool invocations and captures results.

    Requires a reference to the skill registry (injected at construction
    or set later) so it can look up tool implementations by name.
    """

    def __init__(self) -> None:
        self._registry = None  # Set in T03 when SkillRegistry is wired up

    async def execute_step(
        self,
        step: RunStep,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a single run step and return a structured result.

        Args:
            step: The validated step to execute (must have passed policy).
            context: Runtime context (workspace_root, session info, etc.).

        Returns:
            A ToolResult envelope with timing, output, and error info.

        Raises:
            ExecutionError: If the tool cannot be found or crashes.
        """
        now = datetime.now(timezone.utc).isoformat()
        logger.info("Executor stub: would execute %s with %s", step.tool, step.args)
        return ToolResult(
            tool_name=step.tool,
            status="error",
            input=step.args,
            error="Executor not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
