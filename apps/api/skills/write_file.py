"""
write_file — Create or overwrite a text file inside the workspace.

Risk level: Medium
Approval required: Yes
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..models.tool_manifest import (
    ExecutionContext,
    RiskLevel,
    ToolManifest,
    ToolResult,
)
from .base import BaseTool, _now_iso

logger = logging.getLogger(__name__)


class WriteFileTool(BaseTool):
    """Create, overwrite, or append to a text file in the workspace."""

    def get_manifest(self) -> ToolManifest:
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
                    "mode": {"type": "string"},
                },
            },
            failure_modes=["path_outside_workspace", "permission_denied", "file_exists_on_create"],
        )

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        started_at = _now_iso()

        path_str = args.get("path", "")
        content = args.get("content", "")
        mode = args.get("mode", "create")

        workspace = Path(context.workspace_root).resolve()
        target = Path(path_str)
        if not target.is_absolute():
            target = (workspace / target).resolve()
        else:
            target = target.resolve()

        # Containment check
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started_at)

        try:
            # Ensure parent directories exist
            target.parent.mkdir(parents=True, exist_ok=True)

            if mode == "create" and target.exists():
                return self._error(
                    args,
                    f"File already exists (mode=create): {target.relative_to(workspace)}",
                    started_at,
                )

            if mode == "append":
                with open(target, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                # create or overwrite
                target.write_text(content, encoding="utf-8")

            bytes_written = len(content.encode("utf-8"))

        except PermissionError as exc:
            return self._error(args, f"Permission denied: {exc}", started_at)
        except OSError as exc:
            return self._error(args, f"Write error: {exc}", started_at)

        return self._success(
            args,
            {
                "path": str(target.relative_to(workspace)),
                "bytes_written": bytes_written,
                "mode": mode,
            },
            started_at,
            artifacts=[str(target.relative_to(workspace))],
        )
