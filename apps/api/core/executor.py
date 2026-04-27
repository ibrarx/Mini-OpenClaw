"""
Execution manager — runs validated tools and captures results.

The executor only runs tools AFTER the policy engine has cleared them.
Every execution is audit-logged with timing, inputs, outputs, and errors.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.audit import AuditLogger
from ..models.step import RunStep, StepStatus
from ..models.tool_manifest import ExecutionContext, ToolResult
from ..skills.base import BaseTool
from ..skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Raised when tool execution fails unexpectedly."""
    pass


class Executor:
    """
    Invokes tools after policy validation.

    Captures timing, output, errors, and artifacts for every execution.
    All actions are audit-logged.
    """

    def __init__(self, registry: SkillRegistry, audit: AuditLogger) -> None:
        self.registry = registry
        self.audit = audit

    async def execute_step(
        self,
        step: RunStep,
        context: ExecutionContext,
        run_id: str,
    ) -> ToolResult:
        """
        Execute a single plan step.

        Args:
            step: The run step to execute.
            context: Runtime context (workspace, session, etc.).
            run_id: The parent run identifier.

        Returns:
            ToolResult envelope with execution details.
        """
        tool = self.registry.get_tool(step.tool)
        if tool is None:
            error_msg = f"Tool not found: {step.tool}"
            logger.error(error_msg)
            await self.audit.log_event(
                event_type="tool_execution_error",
                run_id=run_id,
                step_id=step.step_id,
                details={"tool": step.tool, "error": error_msg},
            )
            return ToolResult(
                tool_name=step.tool,
                status="error",
                risk_level=step.risk_level,
                input=step.args,
                error=error_msg,
                started_at=ToolResult.now_iso(),
                finished_at=ToolResult.now_iso(),
            )

        # Validate arguments against schema
        validation = tool.validate_args(step.args)
        if not validation.valid:
            error_msg = f"Argument validation failed: {'; '.join(validation.errors)}"
            logger.warning("Step %s: %s", step.step_id, error_msg)
            await self.audit.log_event(
                event_type="tool_validation_error",
                run_id=run_id,
                step_id=step.step_id,
                details={"tool": step.tool, "args": step.args, "errors": validation.errors},
            )
            return ToolResult(
                tool_name=step.tool,
                status="error",
                risk_level=step.risk_level,
                input=step.args,
                error=error_msg,
                started_at=ToolResult.now_iso(),
                finished_at=ToolResult.now_iso(),
            )

        # Execute
        logger.info("Executing step %s: %s(%s)", step.step_id, step.tool, step.args)
        try:
            result = await tool.execute(step.args, context)
        except Exception as exc:
            error_msg = f"Unexpected execution error: {exc}"
            logger.error("Step %s: %s", step.step_id, error_msg, exc_info=True)
            result = ToolResult(
                tool_name=step.tool,
                status="error",
                risk_level=step.risk_level,
                input=step.args,
                error=error_msg,
                started_at=ToolResult.now_iso(),
                finished_at=ToolResult.now_iso(),
            )

        # Audit log
        await self.audit.log_event(
            event_type="tool_execution",
            run_id=run_id,
            step_id=step.step_id,
            details={
                "tool": step.tool,
                "status": result.status,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "error": result.error,
            },
        )

        return result
