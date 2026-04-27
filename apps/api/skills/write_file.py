"""
write_file tool — create or overwrite a text file inside the workspace.

Risk level: Medium. Approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class WriteFileTool(BaseTool):
    """Create or overwrite a text file inside the workspace."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="write_file",
            description="Create or overwrite a text file inside the workspace.",
            risk_level=RiskLevel.MEDIUM,
            approval_required=True,
            read_scope="",
            write_scope="workspace",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["create", "overwrite", "append"]},
                },
                "required": ["path", "content", "mode"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "bytes_written": {"type": "integer"},
                },
            },
            failure_modes=["path_outside_workspace", "permission_denied", "disk_full"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="write_file",
            status="error",
            risk_level=RiskLevel.MEDIUM,
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
