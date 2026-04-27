"""search_in_files tool — recursive grep-like search inside the workspace."""
from __future__ import annotations
import fnmatch, re
from pathlib import Path
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool, _now_iso

MAX_MATCHES = 200

class SearchInFilesTool(BaseTool):
    """Search for keywords or patterns across text files in the workspace."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="search_in_files", description="Search for keywords or patterns across text files in the workspace.",
            risk_level=RiskLevel.SAFE, approval_required=False, read_scope="workspace",
            input_schema={"type":"object","properties":{"path":{"type":"string"},"query":{"type":"string"},"file_glob":{"type":"string"}},"required":["path","query"],"additionalProperties":False},
            output_schema={"type":"object","properties":{"matches":{"type":"array"},"total_matches":{"type":"integer"}}},
            failure_modes=["path_not_found","invalid_pattern"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        started_at = _now_iso()
        path_str = args.get("path","."); query = args.get("query",""); file_glob = args.get("file_glob","*")
        if not query:
            return self._error(args, "Empty search query", started_at)
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
            return self._error(args, f"Path not found: {target}", started_at)
        try:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
        except re.error as exc:
            return self._error(args, f"Invalid pattern: {exc}", started_at)
        matches: list[dict[str,Any]] = []; total = 0
        files = [target] if target.is_file() else sorted(target.rglob("*"))
        for fp in files:
            if not fp.is_file() or not fnmatch.fnmatch(fp.name, file_glob):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    total += 1
                    if len(matches) < MAX_MATCHES:
                        matches.append({"file": str(fp.relative_to(workspace)), "line_number": ln, "line": line.rstrip()})
        return self._success(args, {"matches": matches, "total_matches": total, "truncated": total > MAX_MATCHES}, started_at)
