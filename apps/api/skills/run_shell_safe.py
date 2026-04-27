"""
run_shell_safe tool — execute an allowlisted command inside the workspace.

Risk level: Medium to High. Approval required.
Full implementation in T03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool


class RunShellSafeTool(BaseTool):
    """Execute a limited allowlisted command inside the workspace."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="run_shell_safe",
            description="Execute a limited allowlisted command inside the workspace.",
            risk_level=RiskLevel.HIGH,
            approval_required=True,
            read_scope="workspace",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "enum": ["pwd", "ls", "find", "cat", "grep"]},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                },
                "required": ["command", "args", "cwd"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "stdout": {"type": "string"},
                    "stderr": {"type": "string"},
                    "exit_code": {"type": "integer"},
                },
            },
            failure_modes=["command_not_allowed", "dangerous_args", "timeout"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(
            tool_name="run_shell_safe",
            status="error",
            risk_level=RiskLevel.HIGH,
            input=args,
            error="Not yet implemented (T03).",
            started_at=now,
            finished_at=now,
        )
