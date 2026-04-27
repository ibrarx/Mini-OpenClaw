"""skills/write_file — Create or overwrite a text file inside the workspace."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from apps.api.models.run import RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

class WriteFileTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(name="write_file", description="Create or overwrite a text file inside the workspace.",
                            risk_level=RiskLevel.MEDIUM, approval_required=True,
                            input_schema={"type":"object","properties":{"path":{"type":"string"},
                            "content":{"type":"string"},
                            "mode":{"type":"string","enum":["create","overwrite","append"]}},
                            "required":["path","content","mode"]})

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / args["path"]).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started)
        mode = args.get("mode", "create")
        content = args.get("content", "")
        if mode == "create" and target.exists():
            return self._error(args, f"File already exists: {args['path']} (use overwrite)", started)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with target.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                target.write_text(content, encoding="utf-8")
        except (PermissionError, OSError) as exc:
            return self._error(args, f"Write failed: {exc}", started)
        return self._success(args, {"path": args["path"], "mode": mode,
                                     "bytes_written": len(content.encode("utf-8"))}, started)
