"""search_memory tool — retrieve relevant facts or prior task summaries."""
from __future__ import annotations
from typing import Any
from ..models.step import RiskLevel, ToolResult
from ..models.tool_manifest import ToolManifest
from .base import BaseTool, _now_iso

class SearchMemoryTool(BaseTool):
    """Retrieve relevant facts or prior task summaries from memory."""

    @classmethod
    def get_manifest(cls) -> ToolManifest:
        return ToolManifest(
            name="search_memory", description="Retrieve relevant facts or prior task summaries from memory.",
            risk_level=RiskLevel.SAFE, approval_required=False, read_scope="memory",
            input_schema={"type":"object","properties":{"query":{"type":"string"},"memory_type":{"type":"string","enum":["fact","episode","summary"]},"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["query"],"additionalProperties":False},
            output_schema={"type":"object","properties":{"results":{"type":"array"},"total":{"type":"integer"}}},
            failure_modes=["database_error"],
        )

    async def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        started_at = _now_iso()
        query = args.get("query",""); memory_type = args.get("memory_type"); limit = args.get("limit",10)
        if not query.strip():
            return self._error(args, "Empty search query", started_at)
        db = context.get("db")
        if db is None:
            return self._error(args, "No database connection in context", started_at)
        try:
            from ..memory.retrieval import MemoryRetrieval
            from ..models.memory_item import MemoryType
            mt = MemoryType(memory_type) if memory_type else None
            retrieval = MemoryRetrieval(db)
            items = await retrieval.search(query=query, memory_type=mt, limit=limit)
        except Exception as exc:
            return self._error(args, f"Memory search failed: {exc}", started_at)
        results = [{"id":i.id,"content":i.content,"memory_type":i.memory_type,"source":i.source,"confidence":i.confidence,"created_at":i.created_at} for i in items]
        return self._success(args, {"items": results, "total": len(results)}, started_at)
