"""
search_memory — Retrieve relevant facts or prior task summaries.

Risk level: Safe
Approval required: No
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..memory.retrieval import MemoryRetrieval
from ..models.tool_manifest import (
    ExecutionContext,
    RiskLevel,
    ToolManifest,
    ToolResult,
)
from .base import BaseTool, _now_iso

logger = logging.getLogger(__name__)


class SearchMemoryTool(BaseTool):
    """Query memory for facts, episodes, or summaries."""

    def get_manifest(self) -> ToolManifest:
        return ToolManifest(
            name="search_memory",
            description="Retrieve relevant facts or prior task summaries.",
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            read_scope="memory",
            write_scope="",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "memory_type": {
                        "type": "string",
                        "enum": ["fact", "episode", "summary"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                    "total": {"type": "integer"},
                },
            },
            failure_modes=["database_error"],
        )

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        started_at = _now_iso()

        query = args.get("query", "")
        memory_type = args.get("memory_type")
        limit = args.get("limit", 10)

        if not query.strip():
            return self._error(args, "Empty search query", started_at)

        if not context.db_path:
            return self._error(args, "No database path in context", started_at)

        try:
            retrieval = MemoryRetrieval(Path(context.db_path))
            items = await retrieval.search(
                query=query,
                memory_type=memory_type,
                limit=limit,
            )
        except Exception as exc:
            return self._error(args, f"Memory search failed: {exc}", started_at)

        results = [
            {
                "id": item.id,
                "content": item.content,
                "memory_type": item.memory_type.value,
                "source": item.source,
                "confidence": item.confidence,
                "created_at": item.created_at,
            }
            for item in items
        ]

        return self._success(
            args,
            {"items": results, "total": len(results)},
            started_at,
        )
