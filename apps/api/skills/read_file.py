"""read_file tool — read a text file inside the workspace."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool, _now_iso

MAX_FILE_SIZE = 100 * 1024

class ReadFileTool(BaseTool):
    """Read text file content with optional offset and limit."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="read_file", description="Read a text file inside the workspace.",
            risk_level=RiskLevel.SAFE, approval_required=False,
            read_scope="workspace",
            input_schema={"type":"object","properties":{"path":{"type":"string"},"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":5000}},"required":["path"],"additionalProperties":False},
            output_schema={"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},"size":{"type":"integer"}}},
            failure_modes=["file_not_found","permission_denied","binary_file","file_too_large"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        started_at = _now_iso()
        path_str = args.get("path", ""); offset = args.get("offset", 0); limit = args.get("limit", 5000)
        workspace = Path(context["workspace_root"]).resolve()
        target = Path(path_str)
        if not target.is_absolute():
            target = (workspace / target).resolve()
        else:
            target = target.resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started_at)
        if not target.exists():
            return self._error(args, f"File not found: {target}", started_at)
        if not target.is_file():
            return self._error(args, f"Not a file: {target}", started_at)
        file_size = target.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return self._error(args, f"File too large: {file_size} bytes (max {MAX_FILE_SIZE})", started_at)
        try:
            raw = target.read_bytes()
            if b"\x00" in raw[:8192]:
                return self._error(args, "Binary file detected — cannot read as text", started_at)
            text = raw.decode("utf-8", errors="replace")
        except PermissionError as exc:
            return self._error(args, f"Permission denied: {exc}", started_at)
        except OSError as exc:
            return self._error(args, f"Read error: {exc}", started_at)
        lines = text.splitlines(keepends=True)
        total_lines = len(lines); selected = lines[offset:offset+limit]; content = "".join(selected)
        truncated = (offset + limit) < total_lines
        return self._success(args, {"path": str(target.relative_to(workspace)), "content": content, "size": file_size, "total_lines": total_lines, "truncated": truncated}, started_at)
