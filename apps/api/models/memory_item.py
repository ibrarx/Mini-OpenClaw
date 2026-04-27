"""
Pydantic models for memory items.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Categories of memory."""

    FACT = "fact"
    EPISODE = "episode"
    SUMMARY = "summary"


class MemoryVisibility(str, Enum):
    """Visibility levels for memory items."""

    SYSTEM = "system"
    USER_VISIBLE = "user_visible"
    RESTRICTED = "restricted"


class MemoryItem(BaseModel):
    """A single memory record."""

    id: str = ""
    workspace_id: str = "default"
    memory_type: MemoryType = MemoryType.FACT
    content: str = ""
    summary: str | None = None
    source: str | None = None
    confidence: float = 0.5
    visibility: MemoryVisibility = MemoryVisibility.USER_VISIBLE
    created_at: str = ""
    updated_at: str = ""
    run_id: str | None = None


class MemoryQuery(BaseModel):
    """Parameters for searching memory."""

    query: str = ""
    memory_type: MemoryType | None = None
    workspace_id: str = "default"
    limit: int = Field(default=10, ge=1, le=50)
