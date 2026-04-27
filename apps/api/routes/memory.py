"""
Memory endpoints: list, search, export, stats, delete.

Provides read access to the memory store, keyword search,
JSON export for evaluators, and item management.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_db
from ..memory.manager import MemoryManager
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
        workspace_id=body.workspace_id,
        memory_type=body.memory_type,
        limit=body.limit,
    )

    return [item.model_dump() for item in items]


@router.get("/memory/export")
async def export_memory(
    workspace_id: str = Query(default="default"),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Export all memory as formatted JSON for evaluator inspection."""
    retrieval = MemoryRetrieval(db)

    facts = await retrieval.list_items(
        workspace_id=workspace_id,
        memory_type=MemoryType.FACT,
        limit=1000,
    )
    episodes = await retrieval.list_items(
        workspace_id=workspace_id,
        memory_type=MemoryType.EPISODE,
        limit=1000,
    )
    summaries = await retrieval.list_items(
        workspace_id=workspace_id,
        memory_type=MemoryType.SUMMARY,
        limit=1000,
    )

    # Also export audit events
    audit_rows = await db.execute_fetchall(
        "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 500"
    )
    audit_events = []
    for row in audit_rows:
        event = dict(row)
        if event.get("data"):
            try:
                event["data"] = json.loads(event["data"])
            except (json.JSONDecodeError, TypeError):
                pass
        audit_events.append(event)

    return {
        "facts": [i.model_dump() for i in facts],
        "episodes": [i.model_dump() for i in episodes],
        "summaries": [i.model_dump() for i in summaries],
        "audit_events": audit_events,
    }


@router.get("/memory/stats")
async def memory_stats(
    workspace_id: str = Query(default="default"),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, int]:
    """Return memory item counts by type."""
    manager = MemoryManager(db)
    return await manager.get_stats(workspace_id)


@router.delete("/memory/{item_id}")
async def delete_memory_item(
    item_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Delete a memory item by id."""
    manager = MemoryManager(db)
    deleted = await manager.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return {"deleted": True, "item_id": item_id}
