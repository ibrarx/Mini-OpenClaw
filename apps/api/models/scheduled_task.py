"""models/scheduled_task — Pydantic model for scheduled tasks."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"


class TaskStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ScheduledTask(BaseModel):
    """A task scheduled for future or recurring execution."""

    id: str
    workspace_id: str = "default"
    session_id: str
    message: str
    schedule_type: ScheduleType
    run_at: str | None = None
    interval_seconds: int | None = None
    last_run_at: str | None = None
    next_run_at: str
    status: TaskStatus = TaskStatus.ACTIVE
    created_at: str
    updated_at: str
    run_count: int = 0
    max_runs: int = 0  # 0 = unlimited (for interval)
    last_run_id: str | None = None
    error: str | None = None
    # Pre-approval: tools the user approved at schedule-creation time
    pre_approved_tools: list[str] = []
    # For recurring tasks: True = pre-approval covers all future runs,
    # False = ask for approval each time (pre_approved_tools ignored after first run)
    approve_all_runs: bool = False
