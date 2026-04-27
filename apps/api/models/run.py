"""
models/run — Pydantic models for runs and plans.
Matches the Run, Plan, and PlanStep interfaces in the frontend types.ts.
"""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

class RunStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"

class RiskLevel(str, Enum):
    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"

class ToolResult(BaseModel):
    tool_name: str
    status: str
    risk_level: RiskLevel = RiskLevel.SAFE
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
    artifacts: list[str] = Field(default_factory=list)

class PlanStep(BaseModel):
    step_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.SAFE
    status: StepStatus = StepStatus.PENDING
    result: ToolResult | None = None
    reasoning: str | None = None

class Plan(BaseModel):
    task_type: str = "tool_needed"
    confidence: float = 0.0
    reasoning: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    direct_response: str | None = None

class Run(BaseModel):
    run_id: str
    session_id: str
    workspace_id: str = "default"
    status: RunStatus = RunStatus.IDLE
    user_message: str = ""
    plan: Plan | None = None
    final_response: str | None = None
    created_at: str = ""
    updated_at: str = ""
