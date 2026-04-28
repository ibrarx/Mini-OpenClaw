"""skills/search_in_files — Search for text patterns across workspace files."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from apps.api.models.run import RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

class SearchInFilesTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(name="search_in_files",
                            description="Search for keywords or patterns across text files in the workspace.",
                            risk_level=RiskLevel.SAFE, approval_required=False,
                            input_schema={"type":"object","properties":{"path":{"type":"string"},
                            "query":{"type":"string"},"file_glob":{"type":"string"}},
                            "required":["path","query"]})

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / args["path"]).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started)
        if not target.exists():
            return self._error(args, f"Path does not exist: {args['path']}", started)
        query = args["query"].lower()
        file_glob = args.get("file_glob", "*")
        matches: list[dict[str, Any]] = []
        files = target.rglob(file_glob) if target.is_dir() else [target]
        for fpath in files:
            if not fpath.is_file(): continue
            try:
                fpath.relative_to(workspace)
            except ValueError:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                if query in line.lower():
                    matches.append({"file": str(fpath.relative_to(workspace)), "line": ln, "content": line.strip()[:200]})
                    if len(matches) >= 100: break
            if len(matches) >= 100: break
        return self._success(args, {"query": args["query"], "matches": matches,
                                     "total": len(matches), "truncated": len(matches) >= 100}, started)
