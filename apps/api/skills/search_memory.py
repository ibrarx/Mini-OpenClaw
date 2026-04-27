"""
search_memory tool — retrieve relevant facts or prior task summaries.

Risk level: Safe. No approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class SearchMemoryTool(BaseTool):
    """Retrieve relevant facts or prior task summaries from memory."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="search_memory",
            description="Retrieve relevant facts or prior task summaries from memory.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="memory",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "memory_type": {"type": "string", "enum": ["fact", "episode", "summary"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array"},
                    "total": {"type": "integer"},
                },
            },
            failure_modes=["database_error"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="search_memory",
            status="error",
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
