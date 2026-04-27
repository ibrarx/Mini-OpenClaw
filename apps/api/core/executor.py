"""
Execution manager — runs validated tools.
Invokes tools only after policy validation. Captures outputs, timing, errors.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from ..models.step import RunStep, ToolResult
from ..skills.registry import SkillRegistry
from .audit import AuditLogger

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Raised when tool execution fails unexpectedly."""


class Executor:
    """Executes validated tool invocations and captures results."""

    def __init__(self, registry: SkillRegistry | None = None, audit: AuditLogger | None = None) -> None:
        self._registry = registry
        self._audit = audit

    async def execute_step(
        self,
        step: RunStep,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a single run step and return a structured result."""
        now = datetime.now(timezone.utc).isoformat()
        if self._registry is None:
            return ToolResult(tool_name=step.tool, status="error", input=step.args, error="No skill registry configured.", started_at=now, finished_at=now)

        tool_cls = self._registry.get_tool(step.tool)
        if tool_cls is None:
            error_msg = f"Tool not found: {step.tool}"
            if self._audit:
                await self._audit.log_event("tool_execution_error", run_id=step.run_id, step_id=step.step_id, details={"error": error_msg})
            return ToolResult(tool_name=step.tool, status="error", input=step.args, error=error_msg, started_at=now, finished_at=now)

        # Validate args
        validation = tool_cls.validate_args(step.args)
        if not validation.valid:
            error_msg = f"Argument validation failed: {'; '.join(validation.errors)}"
            return ToolResult(tool_name=step.tool, status="error", input=step.args, error=error_msg, started_at=now, finished_at=now)

        # Execute
        logger.info("Executing step %s: %s(%s)", step.step_id, step.tool, step.args)
        try:
            instance = tool_cls()
            result = await instance.execute(step.args, context or {})
        except Exception as exc:
            error_msg = f"Unexpected execution error: {exc}"
            logger.error("Step %s: %s", step.step_id, error_msg, exc_info=True)
            result = ToolResult(tool_name=step.tool, status="error", input=step.args, error=error_msg, started_at=now, finished_at=now)

        if self._audit:
            await self._audit.log_event("tool_execution", run_id=step.run_id, step_id=step.step_id,
                details={"tool": step.tool, "status": result.status, "error": result.error})

        return result
