"""
list_files tool — list directory contents inside the workspace.

Risk level: Safe. No approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class ListFilesTool(BaseTool):
    """List files and directories inside an allowed workspace path."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="list_files",
            description="List files and directories inside an allowed workspace path.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="workspace",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean", "default": False},
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "entries": {"type": "array"},
                },
                "required": ["path", "entries"],
            },
            failure_modes=["path_not_found", "permission_denied"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="list_files",
            status="error",
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
