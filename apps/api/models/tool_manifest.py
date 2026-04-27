"""
Pydantic models for tool manifests.

Every registered tool declares its capabilities, risk level,
and JSON schemas so the planner and policy engine can reason
about it without importing the tool code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .step import RiskLevel


class ToolManifest(BaseModel):
    """Declarative manifest for a registered tool."""

    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.SAFE
    approval_required: bool = False
    read_scope: str = ""
    write_scope: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permission_scope: str = ""
    failure_modes: list[str] = Field(default_factory=list)
