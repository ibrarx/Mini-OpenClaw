"""
Pydantic models for memory items.

Covers fact, episode, and summary memory types.
See 04-memory-model.md for schema design.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Categories of stored memory."""

    FACT = "fact"
    EPISODE = "episode"
    SUMMARY = "summary"


class Visibility(str, Enum):
    """Who can see a memory item."""

    SYSTEM = "system"
    USER_VISIBLE = "user_visible"
    RESTRICTED = "restricted"


class MemoryItem(BaseModel):
    """A single memory record (fact, episode, or summary)."""

    id: str
    workspace_id: str = "default"
    memory_type: MemoryType
    content: str
    summary: str | None = None
    source: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    visibility: Visibility = Visibility.USER_VISIBLE
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str | None = None


class AuditEvent(BaseModel):
    """An append-only audit log entry."""

    id: str
    event_type: str
    run_id: str | None = None
    step_id: str | None = None
    details: dict = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
