"""
Memory manager — write, update, and delete memory items.

Minimal V1 implementation backing the remember_fact and search_memory
tools. Full expansion in T05.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..models.memory_item import MemoryItem, MemoryType, MemoryVisibility

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages memory item persistence in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def store_fact(
        self,
        content: str,
        source: str = "",
        confidence: float = 0.5,
        workspace_id: str = "default",
        run_id: str | None = None,
    ) -> MemoryItem:
        """
        Persist a new fact to the memory_items table.

        Returns the created MemoryItem.
        """
        item = MemoryItem(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            memory_type=MemoryType.FACT,
            content=content,
            summary=content[:200],
            source=source,
            confidence=confidence,
            visibility=MemoryVisibility.USER_VISIBLE,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            run_id=run_id,
        )

        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                """
                INSERT INTO memory_items
                    (id, workspace_id, memory_type, content, summary, source,
                     confidence, visibility, created_at, updated_at, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.workspace_id,
                    item.memory_type.value,
                    item.content,
                    item.summary,
                    item.source,
                    item.confidence,
                    item.visibility.value,
                    item.created_at,
                    item.updated_at,
                    item.run_id,
                ),
            )
            await conn.commit()

        logger.info("Stored fact %s: %s", item.id, content[:80])
        return item


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
