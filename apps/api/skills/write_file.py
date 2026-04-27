"""write_file tool — create or overwrite a text file inside the workspace."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool, _now_iso

class WriteFileTool(BaseTool):
    """Create, overwrite, or append to a text file in the workspace."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="write_file", description="Create or overwrite a text file inside the workspace.",
            risk_level=RiskLevel.MEDIUM, approval_required=True, write_scope="workspace",
            input_schema={"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},"mode":{"type":"string","enum":["create","overwrite","append"]}},"required":["path","content","mode"],"additionalProperties":False},
            output_schema={"type":"object","properties":{"path":{"type":"string"},"bytes_written":{"type":"integer"}}},
            failure_modes=["path_outside_workspace","permission_denied","disk_full"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        started_at = _now_iso()
        path_str = args.get("path",""); content = args.get("content",""); mode = args.get("mode","create")
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
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "create" and target.exists():
                return self._error(args, f"File already exists (mode=create): {target.relative_to(workspace)}", started_at)
            if mode == "append":
                with open(target, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                target.write_text(content, encoding="utf-8")
            bytes_written = len(content.encode("utf-8"))
        except PermissionError as exc:
            return self._error(args, f"Permission denied: {exc}", started_at)
        except OSError as exc:
            return self._error(args, f"Write error: {exc}", started_at)
        return self._success(args, {"path": str(target.relative_to(workspace)), "bytes_written": bytes_written, "mode": mode}, started_at, artifacts=[str(target.relative_to(workspace))])
