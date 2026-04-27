"""remember_fact tool — persist a stable user or workspace fact in memory."""
from __future__ import annotations
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from ..models.memory_item import MemoryType
from .base import BaseTool, _now_iso


class RememberFactTool(BaseTool):
    """Persist a stable user or workspace fact in memory."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="remember_fact",
            description="Persist a stable user or workspace fact in memory.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            write_scope="memory",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "source": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["content", "source"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "stored": {"type": "boolean"},
                },
            },
            failure_modes=["database_error"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        """Store a fact using MemoryManager.store_fact with duplicate detection.

        Args:
            args: Tool arguments (content, source, confidence).
            context: Runtime context including db connection.

        Returns:
            Structured ToolResult with the stored memory id.
        """
        started_at = _now_iso()
        content = args.get("content", "")
        source = args.get("source", "user")
        confidence = args.get("confidence", 0.8)

        if not content.strip():
            return self._error(args, "Empty fact content", started_at)

        db = context.get("db")
        if db is None:
            return self._error(args, "No database connection in context", started_at)

        try:
            from ..memory.manager import MemoryManager
            manager = MemoryManager(db)
            item = await manager.store_fact(
                content=content,
                source=source,
                confidence=confidence,
                workspace_id=context.get("workspace_id", "default"),
                run_id=context.get("run_id"),
            )
        except Exception as exc:
            return self._error(args, f"Failed to store fact: {exc}", started_at)

        return self._success(
            args,
            {"memory_id": item.id, "content": item.content, "stored": True},
            started_at,
        )
