"""
models/run — Pydantic models for runs and plans.

Supports both the legacy plan-and-execute path and the ReAct loop.
ReAct additions: RetryPolicy, Observation, Run.iterations/max_iterations/observations,
and RunStatus.REACTING.
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
    REACTING = "reacting"
    REFLECTING = "reflecting"
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


class ErrorKind(str, Enum):
    """Classifies tool failures so the executor knows how to respond.

    TRANSIENT — retry is safe (network timeout, rate limit, lock contention).
    PERMANENT — never retry (bad credentials, not found, validation error).
    SIDE_EFFECT — the action partially/fully succeeded but something broke.
                  Cannot be undone automatically. Must surface to user.
    """
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    SIDE_EFFECT = "side_effect"


class ToolResult(BaseModel):
    tool_name: str
    status: str
    risk_level: RiskLevel = RiskLevel.SAFE
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    error_kind: ErrorKind | None = None
    started_at: str = ""
    finished_at: str = ""
    artifacts: list[str] = Field(default_factory=list)


class RetryPolicy(BaseModel):
    """Controls whether and how a tool retries on transient failure."""
    max_retries: int = 0
    backoff_base: float = 1.0
    idempotent: bool = False


class PlanStep(BaseModel):
    step_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.SAFE
    status: StepStatus = StepStatus.PENDING
    result: ToolResult | None = None
    reasoning: str | None = None


class GoalStatus(str, Enum):
    """Status of a single goal in the hybrid Plan-ReAct checklist."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"


class Goal(BaseModel):
    """One goal in the ReAct checklist."""
    goal_id: str             # "goal_1", "goal_2", etc.
    description: str         # What to achieve (not which tool to use)
    status: GoalStatus = GoalStatus.PENDING


class Plan(BaseModel):
    task_type: str = "tool_needed"
    confidence: float = 0.0
    reasoning: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    direct_response: str | None = None
    goals: list[Goal] = Field(default_factory=list)        # empty when goals disabled
    replan_count: int = 0                                   # stays 0 when replanning disabled


class Observation(BaseModel):
    """One iteration of the ReAct loop: think → act → observe."""
    step_id: str
    iteration: int
    tool: str | None = None        # None for final_answer steps
    args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""             # LLM's Think output
    user_announcement: str = ""     # Friendly message for the UI
    result: ToolResult | None = None
    timestamp: str = ""
    token_estimate: int = 0         # estimated tokens consumed at this iteration
    compression_level: str = ""     # "none" | "partial" | "aggressive" — context compression state


class ReflectionResult(BaseModel):
    """Result of the self-reflection critique."""
    overall_score: float = 1.0
    completeness: float = 1.0
    accuracy: float = 1.0
    clarity: float = 1.0
    issues: list[str] = Field(default_factory=list)
    suggestion: str = ""
    improved: bool = False   # whether the answer was text-rewritten (fallback)
    reentry: bool = False    # whether the agent re-entered the loop to take action
    attempt: int = 0         # which reflection attempt (0 = first)


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
    # ReAct fields
    iterations: int = 0
    max_iterations: int = 10
    observations: list[Observation] = Field(default_factory=list)
    context_window: int = 0         # model's context window size (set at run start)
    model_name: str = ""            # LLM model identifier (for UI display)
    reflection: ReflectionResult | None = None  # self-reflection critique result
    # Sub-agent delegation fields
    parent_run_id: str | None = None  # links child runs to parent
    depth: int = 0                    # 0=top-level, 1=child, 2=grandchild
