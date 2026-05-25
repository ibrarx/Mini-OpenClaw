"""skills/delegate_task — Spawn a sub-agent to handle a sub-task.

The sub-agent runs as a separate Run with its own iteration budget,
goal set, and observations.  The parent agent waits for the result
and receives the child's final_response as tool output.

This enables multi-agent patterns:
- "Analyze tests AND write a report" → two sequential sub-agents
- "Research X, then use the findings to do Y" → delegation + action

Safety guardrails:
- Max delegation depth is enforced (default: 2)
- Max children per parent is enforced (default: 3)
- Child iteration budget is capped (default: 5)
- Children cannot delegate further, write memory, or trigger dreams
"""
from __future__ import annotations

from typing import Any

from apps.api.models.run import RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext, ToolResult


class DelegateTaskTool(BaseTool):
    def __init__(self, *, approval_required: bool = True) -> None:
        self._approval_required = approval_required

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="delegate_task",
            description=(
                "Delegate a sub-task to a separate agent. The sub-agent runs "
                "with its own iteration budget and returns its findings. Use "
                "this when a task has distinct sub-parts that can be handled "
                "independently. The sub-agent has access to the same workspace "
                "and tools (except delegation and memory writes)."
            ),
            risk_level=RiskLevel.MEDIUM,
            approval_required=self._approval_required,
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Clear description of the sub-task for the child agent",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Max iterations for the sub-agent (default: 5, max: 5)",
                        "default": 5,
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = self._now()
        task = args.get("task", "")
        max_iter = min(args.get("max_iterations", 5), 5)  # Hard cap at 5

        if not task:
            return self._error(args, "'task' is required", started)

        if not context.delegate_fn:
            return self._error(
                args,
                "Delegation not available in this context (child runs cannot delegate)",
                started,
            )

        try:
            child_run = await context.delegate_fn(
                parent_run_id=context.run_id,
                task=task,
                workspace_id="",  # empty = inherit from parent
                max_iterations=max_iter,
            )
        except Exception as exc:
            return self._error(args, f"Delegation failed: {exc}", started)

        if child_run is None:
            return self._error(args, "Child run creation failed", started)

        status = child_run.status.value
        if status in ("failed", "cancelled"):
            return self._error(
                args,
                f"Sub-agent {status}: {child_run.final_response or 'unknown error'}",
                started,
            )

        # Count completed goals if the child tracked them
        goals_completed = 0
        if child_run.plan and child_run.plan.goals:
            goals_completed = sum(
                1 for g in child_run.plan.goals if g.status.value == "done"
            )

        return self._success(
            args,
            output={
                "child_run_id": child_run.run_id,
                "response": child_run.final_response,
                "iterations_used": child_run.iterations,
                "goals_completed": goals_completed,
            },
            started_at=started,
        )
