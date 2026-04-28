"""Memory endpoints: list, search, delete, export."""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from apps.api.config import get_settings
from apps.api.memory.manager import MemoryManager
from apps.api.memory.retrieval import MemoryRetrieval

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

class SearchRequest(BaseModel):
    query: str
    memory_type: str | None = None
    limit: int = 10

@router.get("/memory")
async def list_memory(request: Request, workspace_id: str = "default",
                       memory_type: str | None = None, limit: int = 100) -> list[dict]:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)
    items = await mm.list_items(workspace_id=workspace_id, memory_type=memory_type, limit=limit)
    return [i.model_dump() for i in items]

@router.post("/memory/search")
async def search_memory(body: SearchRequest, request: Request) -> list[dict]:
    settings = get_settings()
    retrieval = MemoryRetrieval(settings.resolved_database)
    items = await retrieval.search(query=body.query, memory_type=body.memory_type, limit=body.limit)
    return [i.model_dump() for i in items]

@router.delete("/memory/{item_id}")
async def delete_memory(item_id: str, request: Request) -> dict:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)
    deleted = await mm.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory item not found: {item_id}")
    return {"deleted": True, "id": item_id}

@router.get("/memory/export")
async def export_memory(request: Request, workspace_id: str = "default") -> dict:
    settings = get_settings()
    mm = MemoryManager(settings.resolved_database)
    facts = await mm.list_items(workspace_id=workspace_id, memory_type="fact", limit=1000)
    episodes = await mm.list_items(workspace_id=workspace_id, memory_type="episode", limit=1000)
    summaries = await mm.list_items(workspace_id=workspace_id, memory_type="summary", limit=1000)
    return {
        "facts": [i.model_dump() for i in facts],
        "episodes": [i.model_dump() for i in episodes],
        "summaries": [i.model_dump() for i in summaries],
    }
