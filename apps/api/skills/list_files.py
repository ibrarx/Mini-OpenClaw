"""
list_files — List files and directories inside the workspace.

Risk level: Safe
Approval required: No
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


class ListFilesTool(BaseTool):
    """List files and directories inside an allowed workspace path."""

    def get_manifest(self) -> ToolManifest:
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
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "path": {"type": "string"},
                                "kind": {"type": "string", "enum": ["file", "directory"]},
                            },
                        },
                    },
                },
            },
            failure_modes=["path_not_found", "permission_denied", "path_outside_workspace"],
        )

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        started_at = _now_iso()

        target_str = args.get("path", ".")
        recursive = args.get("recursive", False)
        max_depth = args.get("max_depth", 1)

        workspace = Path(context.workspace_root).resolve()
        target = Path(target_str)
        if not target.is_absolute():
            target = (workspace / target).resolve()
        else:
            target = target.resolve()

        # Containment check
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started_at)

        if not target.exists():
            return self._error(args, f"Path not found: {target}", started_at)

        if not target.is_dir():
            return self._error(args, f"Not a directory: {target}", started_at)

        entries: list[dict[str, str]] = []
        try:
            if recursive:
                self._collect_recursive(target, workspace, entries, max_depth, 0)
            else:
                for item in sorted(target.iterdir()):
                    kind = "directory" if item.is_dir() else "file"
                    entries.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace)),
                        "kind": kind,
                    })
        except PermissionError as exc:
            return self._error(args, f"Permission denied: {exc}", started_at)

        return self._success(
            args,
            {"path": str(target.relative_to(workspace)), "entries": entries},
            started_at,
        )

    def _collect_recursive(
        self,
        directory: Path,
        workspace: Path,
        entries: list[dict[str, str]],
        max_depth: int,
        current_depth: int,
    ) -> None:
        """Recursively collect directory entries up to max_depth."""
        if current_depth >= max_depth:
            return
        try:
            for item in sorted(directory.iterdir()):
                kind = "directory" if item.is_dir() else "file"
                entries.append({
                    "name": item.name,
                    "path": str(item.relative_to(workspace)),
                    "kind": kind,
                })
                if item.is_dir() and current_depth + 1 < max_depth:
                    self._collect_recursive(item, workspace, entries, max_depth, current_depth + 1)
        except PermissionError:
            pass  # Skip directories we can't read
