"""
Memory manager — write, update, and delete memory items.

Full implementation in T05; this file provides the class interface
with method signatures and docstrings.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from ..models.memory_item import MemoryItem, MemoryType, Visibility

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages memory item lifecycle (create, update, delete).

    Args:
        db: Active database connection.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def store(
        self,
        content: str,
        memory_type: MemoryType,
        workspace_id: str = "default",
        source: str | None = None,
        confidence: float = 0.5,
        run_id: str | None = None,
        summary: str | None = None,
    ) -> MemoryItem:
        """Store a new memory item.

        Args:
            content: Human-readable memory text.
            memory_type: Category (fact, episode, summary).
            workspace_id: Logical workspace scope.
            source: Where the memory came from.
            confidence: Confidence score 0.0–1.0.
            run_id: Related run if applicable.
            summary: Short compact summary.

        Returns:
            The created MemoryItem.
        """
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT INTO memory_items
                (id, workspace_id, memory_type, content, summary, source,
                 confidence, visibility, created_at, updated_at, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, workspace_id, memory_type.value, content, summary,
                source, confidence, Visibility.USER_VISIBLE.value, now, now, run_id,
            ),
        )
        await self._db.commit()

        return MemoryItem(
            id=item_id,
            workspace_id=workspace_id,
            memory_type=memory_type,
            content=content,
            summary=summary,
            source=source,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            run_id=run_id,
        )

    async def delete(self, item_id: str) -> bool:
        """Delete a memory item by id.

        Returns:
            True if a row was deleted, False otherwise.
        """
        cursor = await self._db.execute(
            "DELETE FROM memory_items WHERE id = ?", (item_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def update(
        self, item_id: str, content: str | None = None, confidence: float | None = None
    ) -> bool:
        """Update fields on an existing memory item.

        Returns:
            True if the item was found and updated.
        """
        sets: list[str] = []
        params: list[Any] = []
        if content is not None:
            sets.append("content = ?")
            params.append(content)
        if confidence is not None:
            sets.append("confidence = ?")
            params.append(confidence)
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(item_id)

        cursor = await self._db.execute(
            f"UPDATE memory_items SET {', '.join(sets)} WHERE id = ?", params
        )
        await self._db.commit()
        return cursor.rowcount > 0
