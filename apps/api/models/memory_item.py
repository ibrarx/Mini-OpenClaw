"""models/memory_item — Pydantic model for memory items."""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

class MemoryType(str, Enum):
    FACT = "fact"
    EPISODE = "episode"
    SUMMARY = "summary"

class MemoryItem(BaseModel):
    id: str
    workspace_id: str = "default"
    memory_type: MemoryType = MemoryType.FACT
    content: str
    summary: str | None = None
    source: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    visibility: str = "user_visible"
    created_at: str = ""
    updated_at: str = ""
    run_id: str | None = None
