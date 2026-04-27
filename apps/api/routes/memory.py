"""
Memory endpoints: list, search, export.

Provides read access to the memory store and keyword search.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, Query

from ..database import get_db
from ..memory.models import MemorySearchRequest
from ..memory.retrieval import MemoryRetrieval
from ..models.memory_item import MemoryItem, MemoryType

logger = logging.getLogger(__name__)
router = APIRouter(tags=["memory"])


@router.get("/memory")
async def list_memory(
    workspace_id: str = Query(default="default"),
    memory_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """List memory items with optional filters."""
    retrieval = MemoryRetrieval(db)

    mt = MemoryType(memory_type) if memory_type else None

    if q:
        items = await retrieval.search(
            query=q,
            workspace_id=workspace_id,
            memory_type=mt,
            limit=limit,
        )
    else:
        items = await retrieval.list_items(
            workspace_id=workspace_id,
            memory_type=mt,
            limit=limit,
        )

    return [item.model_dump() for item in items]


@router.post("/memory/search")
async def search_memory(
    body: MemorySearchRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """Search memory using keyword matching."""
    retrieval = MemoryRetrieval(db)

    items = await retrieval.search(
        query=body.query,
        memory_type=body.memory_type,
        limit=body.limit,
    )

    return [item.model_dump() for item in items]


@router.get("/memory/export")
async def export_memory(
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Export all memory as formatted JSON for evaluator inspection."""
    retrieval = MemoryRetrieval(db)

    facts = await retrieval.list_items(memory_type=MemoryType.FACT, limit=1000)
    episodes = await retrieval.list_items(memory_type=MemoryType.EPISODE, limit=1000)
    summaries = await retrieval.list_items(memory_type=MemoryType.SUMMARY, limit=1000)

    return {
        "facts": [i.model_dump() for i in facts],
        "episodes": [i.model_dump() for i in episodes],
        "summaries": [i.model_dump() for i in summaries],
    }
