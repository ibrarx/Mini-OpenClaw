"""skills/schedule_task — Schedule a task for future or recurring execution.

The planner can invoke this tool when the user says things like:
  - "Remind me in 5 minutes to check the logs"
  - "Check the workspace for changes every 30 minutes"
  - "Run this scan tomorrow morning"

The tool requires approval because it creates background work that
will execute autonomously.  At runtime, if the scheduled run needs
further approval (e.g. a write_file step), the normal approval flow
kicks in and the UI is notified via SSE events.
"""
from __future__ import annotations

from typing import Any

from apps.api.models.run import RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext, ToolResult


class ScheduleTaskTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="schedule_task",
            description=(
                "Schedule a task to run later or on a recurring basis. "
                "Use this when the user says 'remind me', 'check every X minutes', "
                "'do this later', 'run this at [time]', or any request that implies "
                "future or periodic execution. The user will be asked to approve "
                "the scheduling. Once scheduled, the task runs automatically."
            ),
            risk_level=RiskLevel.MEDIUM,
            approval_required=True,
            input_schema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "The task to execute, as a natural-language instruction. "
                            "This will be passed to the agent as if the user typed it."
                        ),
                    },
                    "delay_minutes": {
                        "type": "integer",
                        "description": (
                            "Minutes to wait before the first run. "
                            "For one-time tasks, this is when it fires. "
                            "For recurring tasks, this is the initial delay before "
                            "the first run (defaults to the interval if not set). "
                            "Minimum 1 minute."
                        ),
                        "default": 0,
                    },
                    "interval_minutes": {
                        "type": "integer",
                        "description": (
                            "Repeat every N minutes. 0 means one-time only. "
                            "Minimum 1 minute for recurring tasks."
                        ),
                        "default": 0,
                    },
                    "max_runs": {
                        "type": "integer",
                        "description": (
                            "Maximum number of times to run (0 = unlimited). "
                            "Only meaningful for recurring tasks."
                        ),
                        "default": 0,
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = self._now()

        message = args.get("message", "").strip()
        if not message:
            return self._error(args, "'message' is required and cannot be empty", started)

        delay_minutes = args.get("delay_minutes", 0)
        interval_minutes = args.get("interval_minutes", 0)
        max_runs = args.get("max_runs", 0)

        # Validate minimums
        if interval_minutes < 0:
            return self._error(args, "interval_minutes must be >= 0", started)
        if delay_minutes < 0:
            return self._error(args, "delay_minutes must be >= 0", started)
        if max_runs < 0:
            return self._error(args, "max_runs must be >= 0", started)

        if not context.schedule_fn:
            return self._error(
                args,
                "Scheduling not available in this context",
                started,
            )

        try:
            task = await context.schedule_fn(
                session_id=f"scheduled_from_{context.run_id}",
                message=message,
                workspace_id=context.workspace_root,  # Will be resolved by scheduler
                delay_minutes=delay_minutes,
                interval_minutes=interval_minutes,
                max_runs=max_runs,
            )
        except Exception as exc:
            return self._error(args, f"Scheduling failed: {exc}", started)

        schedule_desc = (
            f"every {interval_minutes} minute(s)"
            if interval_minutes > 0
            else f"in {max(delay_minutes, 1)} minute(s)"
        )
        if max_runs > 0 and interval_minutes > 0:
            schedule_desc += f" (up to {max_runs} times)"

        return self._success(
            args,
            output={
                "task_id": task.id,
                "schedule_type": task.schedule_type.value,
                "next_run_at": task.next_run_at,
                "description": f"Scheduled: '{message}' — {schedule_desc}",
            },
            started_at=started,
        )
