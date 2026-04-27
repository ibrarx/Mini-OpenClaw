"""
Pydantic models for task runs.

A Run represents one user request flowing through the agent pipeline:
planning → policy validation → execution → response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .step import RunStep


class RunStatus(str, Enum):
    """Lifecycle states for a run."""

    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Planner classification of user intent."""

    DIRECT_ANSWER = "direct_answer"
    TOOL_NEEDED = "tool_needed"
    CLARIFICATION_NEEDED = "clarification_needed"
    MULTI_STEP = "multi_step"


class Plan(BaseModel):
    """Structured plan produced by the planner."""

    task_type: TaskType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    steps: list[RunStep] = Field(default_factory=list)


class Run(BaseModel):
    """A single task run through the agent pipeline."""

    run_id: str
    session_id: str
    workspace_id: str = "default"
    status: RunStatus = RunStatus.IDLE
    user_message: str
    plan: Plan | None = None
    final_response: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# --- Request / response models for API endpoints ---


class ChatRequest(BaseModel):
    """POST /api/chat request body."""

    session_id: str
    message: str
    workspace_id: str = "default"


class ChatResponse(BaseModel):
    """POST /api/chat response body."""

    run_id: str
    status: str


class ApprovalRequest(BaseModel):
    """POST /api/runs/{run_id}/approve request body."""

    step_id: str
    approved: bool
