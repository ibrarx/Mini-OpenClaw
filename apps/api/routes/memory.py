"""Memory endpoints: list, search (hybrid/keyword/vector), delete, export."""
import logging

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

from apps.api.config import get_settings
from apps.api.memory.embeddings import EmbeddingProvider
from apps.api.memory.manager import MemoryManager
from apps.api.memory.retrieval import MemoryRetrieval
from apps.api.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)
router = APIRouter(tags=["memory"])


class SearchRequest(BaseModel):
    query: str
    memory_type: str | None = None
    limit: int = 10
    search_mode: str = "hybrid"  # "hybrid", "keyword", or "vector"


def _get_retrieval() -> MemoryRetrieval:
    """Build a MemoryRetrieval with embedding support."""
    settings = get_settings()
    db_path = settings.resolved_database
    embedder = EmbeddingProvider()
    vectors = VectorStore(db_path)
    return MemoryRetrieval(db_path, embedder, vectors)


@router.get("/memory")
async def list_memory(
    request: Request,
    workspace_id: str = "default",
    memory_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)
    items = await mm.list_items(
        workspace_id=workspace_id, memory_type=memory_type, limit=limit
    )
    return [i.model_dump() for i in items]


@router.post("/memory/search")
async def search_memory(body: SearchRequest, request: Request) -> list[dict]:
    """Search memory with hybrid (default), keyword, or vector mode.

    Returns items with similarity scores when available.
    """
    retrieval = _get_retrieval()
    results = await retrieval.search_with_scores(
        query=body.query,
        memory_type=body.memory_type,
        limit=body.limit,
        search_mode=body.search_mode,
    )
    return [
        {**item.model_dump(), "score": round(score, 4)}
        for item, score in results
    ]


@router.delete("/memory/{item_id}")
async def delete_memory(item_id: str, request: Request) -> dict:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)
    deleted = await mm.delete(item_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Memory item not found: {item_id}"
        )
    return {"deleted": True, "id": item_id}


@router.get("/memory/export")
async def export_memory(
    request: Request, workspace_id: str = "default"
) -> dict:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)
    facts = await mm.list_items(
        workspace_id=workspace_id, memory_type="fact", limit=1000
    )
    episodes = await mm.list_items(
        workspace_id=workspace_id, memory_type="episode", limit=1000
    )
    summaries = await mm.list_items(
        workspace_id=workspace_id, memory_type="summary", limit=1000
    )
    return {
        "facts": [i.model_dump() for i in facts],
        "episodes": [i.model_dump() for i in episodes],
        "summaries": [i.model_dump() for i in summaries],
    }
