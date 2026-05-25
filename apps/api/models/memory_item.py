"""models/memory_item — Pydantic model for memory items."""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    FACT = "fact"
    EPISODE = "episode"
    SUMMARY = "summary"
    STRATEGY = "strategy"
    PREFERENCE = "preference"


class MemoryStatus(str, Enum):
    """Lifecycle status for memory items.

    - ``active``: normal item, included in planner context.
    - ``pending_review``: dream-generated candidate awaiting user confirmation.
    - ``rejected``: dismissed by user, excluded from future dream proposals.
    """
    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


class MemoryItem(BaseModel):
    id: str
    workspace_id: str = "default"
    memory_type: MemoryType = MemoryType.FACT
    content: str
    summary: str | None = None
    source: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    visibility: str = "user_visible"
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""
    run_id: str | None = None
