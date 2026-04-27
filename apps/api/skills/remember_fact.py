"""
remember_fact tool — persist a stable user or workspace fact in memory.

Risk level: Safe. No approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class RememberFactTool(BaseTool):
    """Persist a stable user or workspace fact in memory."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="remember_fact",
            description="Persist a stable user or workspace fact in memory.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="",
            write_scope="memory",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "source": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["content", "source"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "stored": {"type": "boolean"},
                },
            },
            failure_modes=["database_error"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="remember_fact",
            status="error",
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
