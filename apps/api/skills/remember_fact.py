"""
remember_fact — Persist a stable user or workspace fact in memory.

Risk level: Safe
Approval required: No
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..memory.manager import MemoryManager
from ..models.tool_manifest import (
    ExecutionContext,
    RiskLevel,
    ToolManifest,
    ToolResult,
)
from .base import BaseTool, _now_iso

logger = logging.getLogger(__name__)


class RememberFactTool(BaseTool):
    """Persist a durable fact about the user or workspace."""

    def get_manifest(self) -> ToolManifest:
        return ToolManifest(
            name="remember_fact",
            description="Persist a stable user or workspace fact in memory.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="",
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
                    "content": {"type": "string"},
                },
            },
            failure_modes=["database_error"],
        )

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        started_at = _now_iso()

        content = args.get("content", "")
        source = args.get("source", "user")
        confidence = args.get("confidence", 0.5)

        if not content.strip():
            return self._error(args, "Empty fact content", started_at)

        if not context.db_path:
            return self._error(args, "No database path in context", started_at)

        try:
            manager = MemoryManager(Path(context.db_path))
            item = await manager.store_fact(
                content=content,
                source=source,
                confidence=confidence,
                run_id=context.run_id,
            )
        except Exception as exc:
            return self._error(args, f"Failed to store fact: {exc}", started_at)

        return self._success(
            args,
            {"memory_id": item.id, "content": item.content},
            started_at,
        )
