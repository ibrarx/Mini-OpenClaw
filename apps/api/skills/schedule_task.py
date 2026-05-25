"""skills/schedule_task — Schedule a task for future or recurring execution.

The planner can invoke this tool when the user says things like:
  - "Remind me in 5 minutes to check the logs"
  - "Check the workspace for changes every 30 minutes"
  - "Run this scan tomorrow morning"

The tool requires approval because it creates background work that
will execute autonomously.

Pre-approval flow:
  When the planner knows the task will use approval-required tools
  (e.g. write_file, run_shell_safe), it lists them in ``pre_approved_tools``.
  The user sees what tools are being pre-approved in the approval card.
  For recurring tasks, ``approve_all_runs`` controls whether pre-approval
  covers every future run (True) or just the first one (False).
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
                "the scheduling. Once scheduled, the task runs automatically.\n\n"
                "IMPORTANT: If the task will require tools that need approval "
                "(write_file, run_shell_safe), you MUST list them in "
                "pre_approved_tools so the user can approve them upfront. "
                "For recurring tasks, set approve_all_runs=true to avoid "
                "asking the user for approval on every single run."
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
                    "pre_approved_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of tool names that require approval (e.g. "
                            "'write_file', 'run_shell_safe') which the user "
                            "should pre-approve at scheduling time. If the "
                            "scheduled task will create/modify files or run "
                            "shell commands, list those tools here so the user "
                            "can approve them upfront instead of being asked "
                            "every time the task runs."
                        ),
                        "default": [],
                    },
                    "approve_all_runs": {
                        "type": "boolean",
                        "description": (
                            "For recurring tasks: if true, the pre-approval "
                            "covers ALL future runs. If false, the user will "
                            "be asked to approve each run individually. "
                            "Only meaningful when pre_approved_tools is non-empty "
                            "and interval_minutes > 0."
                        ),
                        "default": False,
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
        pre_approved_tools = args.get("pre_approved_tools", [])
        approve_all_runs = args.get("approve_all_runs", False)

        # Validate minimums
        if interval_minutes < 0:
            return self._error(args, "interval_minutes must be >= 0", started)
        if delay_minutes < 0:
            return self._error(args, "delay_minutes must be >= 0", started)
        if max_runs < 0:
            return self._error(args, "max_runs must be >= 0", started)

        # Validate pre_approved_tools are known approval-required tools
        valid_preapproval_tools = {"write_file", "run_shell_safe", "delegate_task"}
        invalid = [t for t in pre_approved_tools if t not in valid_preapproval_tools]
        if invalid:
            return self._error(
                args,
                f"Cannot pre-approve tools that don't require approval: {invalid}. "
                f"Valid options: {sorted(valid_preapproval_tools)}",
                started,
            )

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
                workspace_id=context.workspace_root,
                delay_minutes=delay_minutes,
                interval_minutes=interval_minutes,
                max_runs=max_runs,
                pre_approved_tools=pre_approved_tools,
                approve_all_runs=approve_all_runs,
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

        output: dict[str, Any] = {
            "task_id": task.id,
            "schedule_type": task.schedule_type.value,
            "next_run_at": task.next_run_at,
            "description": f"Scheduled: '{message}' — {schedule_desc}",
        }
        if pre_approved_tools:
            approval_scope = "all future runs" if approve_all_runs else "first run only"
            output["pre_approved_tools"] = pre_approved_tools
            output["approval_scope"] = approval_scope

        return self._success(args, output=output, started_at=started)
