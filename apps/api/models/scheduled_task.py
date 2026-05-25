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
