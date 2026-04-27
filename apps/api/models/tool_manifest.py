"""models/tool_manifest — Pydantic model for tool registration manifests."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from apps.api.models.run import RiskLevel

class ToolManifest(BaseModel):
    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.SAFE
    approval_required: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
