"""
search_in_files tool — search for keywords or patterns across workspace files.

Risk level: Safe. No approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class SearchInFilesTool(BaseTool):
    """Search for keywords or patterns across text files in the workspace."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="search_in_files",
            description="Search for keywords or patterns across text files in the workspace.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="workspace",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "file_glob": {"type": "string"},
                },
                "required": ["path", "query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "matches": {"type": "array"},
                    "total_matches": {"type": "integer"},
                },
            },
            failure_modes=["path_not_found", "invalid_pattern"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="search_in_files",
            status="error",
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
