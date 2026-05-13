"""skills/write_file — Create or overwrite a text file inside the workspace."""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any
from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
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

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=2, backoff_base=1.0, idempotent=True)

    async def validate(self, args: dict[str, Any], context: ToolContext) -> Any:
        """Pre-flight: check that workspace path is valid."""
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / args.get("path", "")).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", self._now(),
                               error_kind=ErrorKind.PERMANENT)
        mode = args.get("mode", "create")
        if mode == "overwrite" and not target.exists():
            # Not an error per se — overwrite on missing file just creates it.
            pass
        return None  # validation passed

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / args["path"]).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Path outside workspace: {target}", started,
                               error_kind=ErrorKind.PERMANENT)
        mode = args.get("mode", "create")
        content = args.get("content", "")
        if mode == "create" and target.exists():
            return self._error(args, f"File already exists: {args['path']} (use overwrite)", started,
                               error_kind=ErrorKind.PERMANENT)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Backup before overwrite for saga compensation
            if mode == "overwrite" and target.exists():
                bak = target.with_suffix(target.suffix + ".bak")
                shutil.copy2(str(target), str(bak))
            if mode == "append":
                with target.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                target.write_text(content, encoding="utf-8")
        except PermissionError as exc:
            return self._error(args, f"Write failed: {exc}", started,
                               error_kind=ErrorKind.PERMANENT)
        except OSError as exc:
            # Disk full, I/O error — transient, may succeed on retry
            return self._error(args, f"Write failed: {exc}", started,
                               error_kind=ErrorKind.TRANSIENT)
        return self._success(args, {"path": args["path"], "mode": mode,
                                     "bytes_written": len(content.encode("utf-8"))}, started)

    async def compensate(self, args: dict[str, Any], context: ToolContext, execution_id: str) -> Any:
        """Restore from .bak if overwrite, or delete if create."""
        started = self._now()
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / args.get("path", "")).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            return self._error(args, f"Compensation failed: path outside workspace", started)
        mode = args.get("mode", "create")
        try:
            if mode == "overwrite":
                bak = target.with_suffix(target.suffix + ".bak")
                if bak.exists():
                    shutil.copy2(str(bak), str(target))
                    bak.unlink()
                    return self._success(args, {"compensated": True, "action": "restored_from_backup"}, started)
                return self._success(args, {"compensated": False, "reason": "no backup found"}, started)
            elif mode == "create":
                if target.exists():
                    target.unlink()
                    return self._success(args, {"compensated": True, "action": "deleted_created_file"}, started)
                return self._success(args, {"compensated": False, "reason": "file not found"}, started)
            else:
                # append — can't undo appends without knowing prior state
                return self._success(args, {"compensated": False, "reason": "append not reversible"}, started)
        except (PermissionError, OSError) as exc:
            return self._error(args, f"Compensation failed: {exc}", started)
