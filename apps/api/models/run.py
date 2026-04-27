"""
Pydantic models for task runs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .step import RunStep


class RunStatus(str, Enum):
    """Possible states for a run."""

    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Types of tasks the planner can classify."""

    DIRECT_ANSWER = "direct_answer"
    TOOL_NEEDED = "tool_needed"
    CLARIFICATION_NEEDED = "clarification_needed"
    MULTI_STEP = "multi_step"


class Plan(BaseModel):
    """Structured plan produced by the planner."""

    task_type: TaskType
    confidence: float = 0.5
    reasoning: str = ""
    steps: list[RunStep] = Field(default_factory=list)


class Run(BaseModel):
    """A task run with plan, steps, and status."""

    run_id: str
    session_id: str
    workspace_id: str = "default"
    status: RunStatus = RunStatus.IDLE
    user_message: str = ""
    plan: Plan | None = None
    final_response: str | None = None
    created_at: str = ""
    updated_at: str = ""
