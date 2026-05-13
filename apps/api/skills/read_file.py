"""skills/read_file — Read a text file inside the workspace."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

class ReadFileTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(name="read_file", description="Read a text file inside the workspace.",
                            risk_level=RiskLevel.SAFE, approval_required=False,
                            input_schema={"type":"object","properties":{"path":{"type":"string"},
                            "offset":{"type":"integer","minimum":0},
                            "limit":{"type":"integer","minimum":1,"maximum":5000}},"required":["path"]})

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=1, idempotent=True)

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / args["path"]).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started,
                               error_kind=ErrorKind.PERMANENT)
        if not target.exists():
            return self._error(args, f"File not found: {args['path']}", started,
                               error_kind=ErrorKind.PERMANENT)
        if not target.is_file():
            return self._error(args, f"Not a file: {args['path']}", started,
                               error_kind=ErrorKind.PERMANENT)
        # Binary file detection: check first 8 KB for null bytes
        try:
            raw = target.read_bytes()[:8192]
        except PermissionError:
            return self._error(args, f"Permission denied: {args['path']}", started,
                               error_kind=ErrorKind.PERMANENT)
        if b"\x00" in raw:
            return self._error(args, f"Binary file detected: {args['path']}", started,
                               error_kind=ErrorKind.PERMANENT)
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return self._error(args, f"Permission denied: {args['path']}", started,
                               error_kind=ErrorKind.PERMANENT)
        offset = args.get("offset", 0)
        limit = args.get("limit", 5000)
        lines = text.splitlines()
        sliced = lines[offset:offset + limit]
        return self._success(args, {"path": args["path"], "content": "\n".join(sliced),
                                     "total_lines": len(lines), "truncated": len(lines) > offset + limit}, started)
