"""
core/executor — Runs validated tools and captures results.

ReAct additions:
- Pre-flight validation via tool.validate()
- Retry with exponential backoff for transient failures
- Saga compensation via compensate_steps()
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any

from apps.api.core.audit import AuditLogger
from apps.api.models.run import PlanStep, ToolResult
from apps.api.skills.base import BaseTool, ToolContext
from apps.api.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, registry: SkillRegistry, audit: AuditLogger) -> None:
        self._registry = registry
        self._audit = audit

    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        """Execute a tool with pre-flight validation and retry logic.

        Flow:
        1. Look up tool in registry
        2. Call tool.validate() — if it returns an error, return immediately
        3. Generate execution_id, set on context
        4. Execute the tool
        5. On failure: retry if tool's retry_policy allows (idempotent + retries > 0)
        6. Return final result
        """
        tool = self._registry.get(tool_name)
        if tool is None:
            logger.error("Tool not found: %s", tool_name)
            return ToolResult(
                tool_name=tool_name, status="error", input=args,
                error=f"Tool not found: {tool_name}",
            )

        # Pre-flight validation
        try:
            validation_error = await tool.validate(args, context)
            if validation_error is not None:
                logger.warning("Tool %s validation failed: %s", tool_name, validation_error.error)
                await self._audit.log(
                    "validation_failed", run_id=context.run_id,
                    step_id=context.step_id,
                    data={"tool": tool_name, "error": validation_error.error},
                )
                return validation_error
        except Exception as exc:
            logger.error("Tool %s validate() raised: %s", tool_name, exc, exc_info=True)
            # Don't block execution on validate() bugs — fall through

        # Generate execution_id for compensation tracking
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        context_with_exec = context.model_copy(update={"execution_id": execution_id})

        await self._audit.log(
            "step_started", run_id=context.run_id, step_id=context.step_id,
            data={"tool": tool_name, "args": args, "execution_id": execution_id},
        )

        # Execute with retry
        retry_policy = tool.retry_policy
        max_attempts = 1 + retry_policy.max_retries
        last_result: ToolResult | None = None

        for attempt in range(max_attempts):
            try:
                result = await tool.execute(args, context_with_exec)
            except Exception as exc:
                logger.error("Tool %s raised: %s", tool_name, exc, exc_info=True)
                result = ToolResult(
                    tool_name=tool_name, status="error", input=args,
                    error=f"Unexpected error: {exc}",
                )

            last_result = result

            if result.status == "success":
                break

            # Should we retry?
            if (
                attempt < max_attempts - 1
                and retry_policy.max_retries > 0
                and retry_policy.idempotent
            ):
                delay = retry_policy.backoff_base * (2 ** attempt)
                logger.info(
                    "Tool %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    tool_name, attempt + 1, max_attempts, delay, result.error,
                )
                await self._audit.log(
                    "step_retrying", run_id=context.run_id,
                    step_id=context.step_id,
                    data={
                        "tool": tool_name, "attempt": attempt + 1,
                        "delay": delay, "error": result.error,
                    },
                )
                await asyncio.sleep(delay)
            else:
                break

        assert last_result is not None
        event = "step_completed" if last_result.status == "success" else "step_failed"
        await self._audit.log(
            event, run_id=context.run_id, step_id=context.step_id,
            data={
                "tool": tool_name, "status": last_result.status,
                "error": last_result.error, "execution_id": execution_id,
            },
        )
        return last_result

    async def compensate_steps(
        self, steps: list[PlanStep], context: ToolContext
    ) -> list[ToolResult]:
        """Run compensations in reverse order (saga rollback)."""
        results = []
        for step in reversed(steps):
            if step.result and step.result.status == "success":
                tool = self._registry.get(step.tool)
                if tool:
                    try:
                        comp_result = await tool.compensate(
                            step.args, context, step.step_id,
                        )
                        results.append(comp_result)
                        await self._audit.log(
                            "step_compensated", run_id=context.run_id,
                            step_id=step.step_id,
                            data={
                                "tool": step.tool,
                                "compensation_status": comp_result.status,
                            },
                        )
                    except Exception as exc:
                        logger.error(
                            "Compensation failed for step %s: %s",
                            step.step_id, exc, exc_info=True,
                        )
                        results.append(ToolResult(
                            tool_name=step.tool, status="error",
                            input=step.args,
                            error=f"Compensation error: {exc}",
                        ))
        return results
