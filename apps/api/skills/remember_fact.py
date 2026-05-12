"""skills/remember_fact — Persist a stable user or workspace fact in memory."""
from __future__ import annotations
from typing import Any
from apps.api.models.run import RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext


class RememberFactTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(name="remember_fact",
                            description="Persist a stable user or workspace fact in memory.",
                            risk_level=RiskLevel.SAFE, approval_required=False,
                            input_schema={"type":"object","properties":{"content":{"type":"string"},
                            "source":{"type":"string"},
                            "confidence":{"type":"number","minimum":0,"maximum":1}},
                            "required":["content","source"]})

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        from apps.api.memory.manager import MemoryManager
        from pathlib import Path
        content = args.get("content", "")
        source = args.get("source", "user")
        confidence = args.get("confidence", 0.8)
        if not content.strip():
            return self._error(args, "Content cannot be empty", started)
        mm = MemoryManager(Path(context.db_path))
        item = await mm.store_fact(content=content, source=source, confidence=confidence,
                                    workspace_id="default", run_id=context.run_id)
        return self._success(args, {"memory_id": item.id, "content": item.content,
                                     "memory_type": item.memory_type}, started)

    async def compensate(self, args: dict[str, Any], context: ToolContext, execution_id: str) -> Any:
        """Soft-delete the memory item created by this tool."""
        started = self._now()
        from apps.api.memory.manager import MemoryManager
        from pathlib import Path
        if not context.db_path:
            return self._error(args, "No db_path in context for compensation", started)
        # We don't have the memory_id here, so delete by run_id + content match
        mm = MemoryManager(Path(context.db_path))
        deleted = await mm.soft_delete_by_run(context.run_id)
        return self._success(args, {"compensated": True, "deleted_count": deleted}, started)
