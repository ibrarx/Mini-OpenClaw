"""
Pydantic models for run steps and step status tracking.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """Possible states for a run step."""

    PENDING = "pending"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"
    FORBIDDEN = "forbidden"


class RunStep(BaseModel):
    """A single step within a run plan."""

    step_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "safe"
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
