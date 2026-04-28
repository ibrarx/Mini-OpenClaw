"""core/executor — Runs validated tools and captures results."""
from __future__ import annotations
import logging
from typing import Any
from apps.api.core.audit import AuditLogger
from apps.api.models.run import ToolResult
from apps.api.skills.base import BaseTool, ToolContext
from apps.api.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, registry: SkillRegistry, audit: AuditLogger) -> None:
        self._registry = registry
        self._audit = audit

    async def execute_tool(self, tool_name: str, args: dict[str, Any], context: ToolContext) -> ToolResult:
        tool = self._registry.get(tool_name)
        if tool is None:
            logger.error("Tool not found: %s", tool_name)
            return ToolResult(tool_name=tool_name, status="error", input=args,
                              error=f"Tool not found: {tool_name}")
        await self._audit.log("step_started", run_id=context.run_id, step_id=context.step_id,
                               data={"tool": tool_name, "args": args})
        try:
            result = await tool.execute(args, context)
        except Exception as exc:
            logger.error("Tool %s raised: %s", tool_name, exc, exc_info=True)
            result = ToolResult(tool_name=tool_name, status="error", input=args,
                                error=f"Unexpected error: {exc}")
        event = "step_completed" if result.status == "success" else "step_failed"
        await self._audit.log(event, run_id=context.run_id, step_id=context.step_id,
                               data={"tool": tool_name, "status": result.status, "error": result.error})
        return result
