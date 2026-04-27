"""
Memory manager — write, update, and delete memory items.

Provides convenience methods for storing facts, episodes, and summaries,
with duplicate detection for facts and rotation for summaries.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from ..models.memory_item import MemoryItem, MemoryType, Visibility

logger = logging.getLogger(__name__)

MAX_SUMMARIES_PER_WORKSPACE = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    """Manages memory item lifecycle (create, update, delete).

    Args:
        db: Active database connection.
        config: Optional settings (unused in V1, reserved for future).
    """

    def __init__(self, db: aiosqlite.Connection, config: Any = None) -> None:
        self._db = db
        self._config = config

    # ------------------------------------------------------------------
    # Core store
    # ------------------------------------------------------------------

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
            confidence: Confidence score 0.0-1.0.
            run_id: Related run if applicable.
            summary: Short compact summary.

        Returns:
            The created MemoryItem.
        """
        item_id = str(uuid.uuid4())
        now = _now()

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

        logger.info("Stored %s memory item %s", memory_type.value, item_id)

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

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def store_fact(
        self,
        content: str,
        source: str,
        workspace_id: str = "default",
        confidence: float = 0.8,
        run_id: str | None = None,
    ) -> MemoryItem:
        """Store a durable fact. Check for duplicates by exact content match.

        Args:
            content: The fact text.
            source: Where this fact came from (run_id, user input, etc.).
            workspace_id: Logical workspace scope.
            confidence: Confidence score 0.0-1.0.
            run_id: Related run if applicable.

        Returns:
            The created (or existing duplicate) MemoryItem.
        """
        existing = await self._db.execute_fetchall(
            """
            SELECT * FROM memory_items
            WHERE workspace_id = ? AND memory_type = ? AND content = ?
            LIMIT 1
            """,
            (workspace_id, MemoryType.FACT.value, content),
        )
        if existing:
            logger.debug("Duplicate fact detected, returning existing item")
            return _row_to_item(existing[0])

        return await self.store(
            content=content,
            memory_type=MemoryType.FACT,
            workspace_id=workspace_id,
            source=source,
            confidence=confidence,
            run_id=run_id,
        )

    async def store_episode(
        self,
        content: str,
        summary: str,
        source: str,
        workspace_id: str = "default",
        run_id: str | None = None,
    ) -> MemoryItem:
        """Store a completed task episode with summary.

        Args:
            content: Full description of what happened.
            summary: Short compact summary for context retrieval.
            source: Where the episode came from.
            workspace_id: Logical workspace scope.
            run_id: Related run if applicable.

        Returns:
            The created MemoryItem.
        """
        return await self.store(
            content=content,
            memory_type=MemoryType.EPISODE,
            workspace_id=workspace_id,
            source=source,
            confidence=1.0,
            run_id=run_id,
            summary=summary,
        )

    async def store_summary(
        self,
        content: str,
        workspace_id: str = "default",
        source: str = "system",
    ) -> MemoryItem:
        """Store a conversation summary. Replaces oldest if too many.

        Keeps at most MAX_SUMMARIES_PER_WORKSPACE summaries per workspace.

        Args:
            content: The summary text.
            workspace_id: Logical workspace scope.
            source: Where the summary came from.

        Returns:
            The created MemoryItem.
        """
        rows = await self._db.execute_fetchall(
            """
            SELECT id FROM memory_items
            WHERE workspace_id = ? AND memory_type = ?
            ORDER BY created_at ASC
            """,
            (workspace_id, MemoryType.SUMMARY.value),
        )
        if len(rows) >= MAX_SUMMARIES_PER_WORKSPACE:
            to_delete = rows[: len(rows) - MAX_SUMMARIES_PER_WORKSPACE + 1]
            for row in to_delete:
                await self._db.execute(
                    "DELETE FROM memory_items WHERE id = ?", (row["id"],)
                )
                logger.debug("Rotated out old summary %s", row["id"])
            await self._db.commit()

        return await self.store(
            content=content,
            memory_type=MemoryType.SUMMARY,
            workspace_id=workspace_id,
            source=source,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_items(
        self,
        workspace_id: str = "default",
        memory_type: str | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """List memory items with optional type filter.

        Args:
            workspace_id: Logical workspace scope.
            memory_type: Optional filter ("fact", "episode", "summary").
            limit: Maximum results to return.

        Returns:
            List of MemoryItem objects ordered by recency.
        """
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]

        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(memory_type)

        where = " AND ".join(clauses)
        params.append(limit)

        rows = await self._db.execute_fetchall(
            f"SELECT * FROM memory_items WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        )
        return [_row_to_item(row) for row in rows]

    async def get_item(self, item_id: str) -> MemoryItem | None:
        """Get a single memory item by id.

        Returns:
            The MemoryItem or None if not found.
        """
        rows = await self._db.execute_fetchall(
            "SELECT * FROM memory_items WHERE id = ?", (item_id,)
        )
        if not rows:
            return None
        return _row_to_item(rows[0])

    # ------------------------------------------------------------------
    # Update / Delete
    # ------------------------------------------------------------------

    async def delete_item(self, item_id: str) -> bool:
        """Delete a memory item by id.

        Returns:
            True if a row was deleted, False otherwise.
        """
        cursor = await self._db.execute(
            "DELETE FROM memory_items WHERE id = ?", (item_id,)
        )
        await self._db.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted memory item %s", item_id)
        return deleted

    async def delete(self, item_id: str) -> bool:
        """Alias for delete_item (backward compatibility)."""
        return await self.delete_item(item_id)

    async def update_fact(self, item_id: str, content: str) -> MemoryItem | None:
        """Update an existing fact's content. Preserve provenance.

        Args:
            item_id: The id of the fact to update.
            content: New content text.

        Returns:
            The updated MemoryItem or None if not found.
        """
        now = _now()
        cursor = await self._db.execute(
            "UPDATE memory_items SET content = ?, updated_at = ? WHERE id = ?",
            (content, now, item_id),
        )
        await self._db.commit()
        if cursor.rowcount == 0:
            return None
        return await self.get_item(item_id)

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
        params.append(_now())
        params.append(item_id)

        cursor = await self._db.execute(
            f"UPDATE memory_items SET {', '.join(sets)} WHERE id = ?", params
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self, workspace_id: str = "default") -> dict:
        """Return counts by type for the UI.

        Returns:
            Dict with keys: total, facts, episodes, summaries.
        """
        rows = await self._db.execute_fetchall(
            """
            SELECT memory_type, COUNT(*) as cnt
            FROM memory_items
            WHERE workspace_id = ?
            GROUP BY memory_type
            """,
            (workspace_id,),
        )
        stats: dict[str, int] = {"total": 0, "facts": 0, "episodes": 0, "summaries": 0}
        for row in rows:
            d = dict(row)
            mt = d["memory_type"]
            count = d["cnt"]
            stats["total"] += count
            if mt == "fact":
                stats["facts"] = count
            elif mt == "episode":
                stats["episodes"] = count
            elif mt == "summary":
                stats["summaries"] = count
        return stats


def _row_to_item(row: aiosqlite.Row) -> MemoryItem:
    """Convert a database row to a MemoryItem model."""
    d = dict(row)
    return MemoryItem(
        id=d["id"],
        workspace_id=d["workspace_id"],
        memory_type=d["memory_type"],
        content=d["content"],
        summary=d.get("summary"),
        source=d.get("source"),
        confidence=d.get("confidence", 0.5),
        visibility=d.get("visibility", "user_visible"),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        run_id=d.get("run_id"),
    )
