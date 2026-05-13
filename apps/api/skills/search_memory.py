"""skills/search_memory — Retrieve facts or summaries from memory. Safe, no approval."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from apps.api.models.run import ErrorKind, RetryPolicy, RiskLevel
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext


def _build_retrieval(db_path_str: str):
    """Build a MemoryRetrieval with embedding support for hybrid search."""
    from apps.api.memory.embeddings import EmbeddingProvider
    from apps.api.memory.retrieval import MemoryRetrieval
    from apps.api.memory.vector_store import VectorStore
    db_path = Path(db_path_str)
    embedder = EmbeddingProvider()
    vectors = VectorStore(db_path)
    return MemoryRetrieval(db_path, embedder, vectors)


class SearchMemoryTool(BaseTool):
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="search_memory",
            description="Retrieve relevant facts or prior task summaries from memory.",
            risk_level=RiskLevel.SAFE, approval_required=False,
            input_schema={"type": "object", "properties": {
                "query": {"type": "string"},
                "memory_type": {"type": "string", "enum": ["fact", "episode", "summary"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            }, "required": ["query"]})

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=1, idempotent=True)

    async def execute(self, args: dict[str, Any], context: ToolContext) -> Any:
        started = self._now()
        query = args.get("query", "")
        if not query.strip():
            return self._error(args, "Query cannot be empty", started)

        retrieval = _build_retrieval(context.db_path)
        items = await retrieval.search(query=query, memory_type=args.get("memory_type"),
                                        limit=args.get("limit", 10), workspace_id="default")
        results = [{"id": i.id, "content": i.content, "memory_type": i.memory_type.value,
                     "confidence": i.confidence, "source": i.source} for i in items]
        return self._success(args, {"query": query, "results": results, "total": len(results)}, started)
