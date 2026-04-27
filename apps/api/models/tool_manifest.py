"""
Pydantic models for tool manifests, results, and execution context.

These models define the contract every tool must satisfy and the
structured envelope every tool result is wrapped in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk classification for a tool or action."""

    SAFE = "safe"
    MEDIUM = "medium"
    HIGH = "high"


class ToolManifest(BaseModel):
    """Declarative manifest for a registered tool."""

    name: str
    description: str
    risk_level: RiskLevel
    approval_required: bool = False
    read_scope: str = ""
    write_scope: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    failure_modes: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """Structured envelope returned by every tool execution."""

    tool_name: str
    status: str  # "success" | "error"
    risk_level: RiskLevel
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
    artifacts: list[str] = Field(default_factory=list)

    @staticmethod
    def now_iso() -> str:
        """Return current UTC time as ISO 8601 string."""
        return datetime.now(timezone.utc).isoformat()


class ExecutionContext(BaseModel):
    """Runtime context passed to every tool execution."""

    workspace_root: str
    session_id: str = ""
    run_id: str = ""
    db_path: str = ""

    model_config = {"arbitrary_types_allowed": True}


class ValidationResult(BaseModel):
    """Result of validating tool arguments against the input schema."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
