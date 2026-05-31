"""skills/list_files — List files and directories inside the workspace."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext, resolve_tool_path

class ListFilesTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(name="list_files", description="List files and directories inside the workspace.",
                            risk_level=RiskLevel.SAFE, approval_required=False,
                            input_schema={"type":"object","properties":{"path":{"type":"string"},
                            "recursive":{"type":"boolean","default":False},
                            "max_depth":{"type":"integer","minimum":1,"maximum":5}},"required":["path"]})

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=1, idempotent=True)

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        try:
            root, target = resolve_tool_path(args["path"], context)
        except ValueError as exc:
            return self._error(args, str(exc), started)
        if not target.exists():
            return self._error(args, f"Path does not exist: {args['path']}", started)
        if not target.is_dir():
            return self._error(args, f"Not a directory: {args['path']}", started)

        recursive = args.get("recursive", False)
        max_depth = args.get("max_depth", 2)
        entries = []
        if recursive:
            entries = self._walk(target, root, max_depth, 0)
        else:
            for item in sorted(target.iterdir()):
                kind = "directory" if item.is_dir() else "file"
                entries.append({"name": item.name, "path": str(item.relative_to(root)), "kind": kind})
        return self._success(args, {"path": args["path"], "entries": entries}, started)

    def _walk(self, d: Path, ws: Path, max_d: int, cur: int) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        if cur >= max_d: return entries
        try:
            for item in sorted(d.iterdir()):
                kind = "directory" if item.is_dir() else "file"
                entries.append({"name": item.name, "path": str(item.relative_to(ws)), "kind": kind})
                if item.is_dir():
                    entries.extend(self._walk(item, ws, max_d, cur + 1))
        except PermissionError:
            pass
        return entries
