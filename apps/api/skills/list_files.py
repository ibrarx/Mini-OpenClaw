"""
list_files tool — list directory contents inside the workspace.

Risk level: Safe. No approval required.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool, _now_iso

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
                "properties": {"path": {"type": "string"}, "entries": {"type": "array"}},
                "required": ["path", "entries"],
            },
            failure_modes=["path_not_found", "permission_denied", "path_outside_workspace"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        started_at = _now_iso()
        target_str = args.get("path", ".")
        recursive = args.get("recursive", False)
        max_depth = args.get("max_depth", 1)
        workspace = Path(context["workspace_root"]).resolve()
        target = Path(target_str)
        if not target.is_absolute():
            target = (workspace / target).resolve()
        else:
            target = target.resolve()
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
                _collect_recursive(target, workspace, entries, max_depth, 0)
            else:
                for item in sorted(target.iterdir()):
                    kind = "directory" if item.is_dir() else "file"
                    entries.append({"name": item.name, "path": str(item.relative_to(workspace)), "kind": kind})
        except PermissionError as exc:
            return self._error(args, f"Permission denied: {exc}", started_at)
        return self._success(args, {"path": str(target.relative_to(workspace)), "entries": entries}, started_at)

def _collect_recursive(directory: Path, workspace: Path, entries: list, max_depth: int, current: int) -> None:
    if current >= max_depth:
        return
    try:
        for item in sorted(directory.iterdir()):
            kind = "directory" if item.is_dir() else "file"
            entries.append({"name": item.name, "path": str(item.relative_to(workspace)), "kind": kind})
            if item.is_dir() and current + 1 < max_depth:
                _collect_recursive(item, workspace, entries, max_depth, current + 1)
    except PermissionError:
        pass
