"""
Pydantic models for memory operations.

These cover request/response shapes for memory endpoints and
internal memory queries, separate from the core MemoryItem model
in models/memory_item.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models.memory_item import MemoryType


class MemorySearchRequest(BaseModel):
    """POST /api/memory/search request body."""

    query: str
    memory_type: MemoryType | None = None
    limit: int = Field(default=10, ge=1, le=50)


class MemoryQuery(BaseModel):
    """Internal query parameters for memory retrieval."""

    workspace_id: str = "default"
    memory_type: MemoryType | None = None
    query: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
