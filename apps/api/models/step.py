"""
Pydantic models for individual steps within a run.

Each step maps to one tool invocation proposed by the planner
and validated by the policy engine.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """Lifecycle states for a single run step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    SKIPPED = "skipped"


class RiskLevel(str, Enum):
    """Tool / step risk classification."""

    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"


class RunStep(BaseModel):
    """One tool invocation within a run plan."""

    step_id: str
    run_id: str = ""
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.SAFE
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class PolicyDecision(BaseModel):
    """Result of the policy engine evaluating a proposed step."""

    allowed: bool
    classification: str  # "safe", "approval_required", "forbidden"
    reason: str = ""
    modified_args: dict[str, Any] | None = None


class ToolResult(BaseModel):
    """Structured envelope returned by every tool execution."""

    tool_name: str
    status: str  # "success" | "error"
    risk_level: RiskLevel = RiskLevel.SAFE
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
    artifacts: list[str] = Field(default_factory=list)
