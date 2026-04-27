"""
read_file tool — read a text file inside the workspace.

Risk level: Safe. No approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class ReadFileTool(BaseTool):
    """Read a text file inside the workspace."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="read_file",
            description="Read a text file inside the workspace.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="workspace",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "size": {"type": "integer"},
                },
            },
            failure_modes=["file_not_found", "permission_denied", "binary_file"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="read_file",
            status="error",
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
