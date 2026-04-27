"""
Memory retrieval — search and retrieve memory context.

Provides keyword search over SQLite for V1. Semantic/embedding
retrieval is a stretch goal.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from ..models.memory_item import MemoryItem, MemoryType

logger = logging.getLogger(__name__)


class MemoryRetrieval:
    """Search and retrieve memory items from SQLite.

    Args:
        db: Active database connection.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def search(
        self,
        query: str,
        workspace_id: str = "default",
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search memory items by keyword.

        Uses LIKE-based matching for V1. Results are ranked by
        recency.

        Args:
            query: Search keywords.
            workspace_id: Scope to a specific workspace.
            memory_type: Optionally filter by memory category.
            limit: Maximum results to return.

        Returns:
            List of matching MemoryItem objects.
        """
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]

        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(memory_type.value)

        if query:
            clauses.append("(content LIKE ? OR summary LIKE ?)")
            like_pattern = f"%{query}%"
            params.extend([like_pattern, like_pattern])

        where = " AND ".join(clauses)
        params.append(limit)

        rows = await self._db.execute_fetchall(
            f"""
            SELECT * FROM memory_items
            WHERE {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        )

        return [self._row_to_item(row) for row in rows]

    async def list_items(
        self,
        workspace_id: str = "default",
        memory_type: MemoryType | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """List memory items with optional type filter.

        Args:
            workspace_id: Scope to a specific workspace.
            memory_type: Optionally filter by memory category.
            limit: Maximum results to return.

        Returns:
            List of MemoryItem objects ordered by recency.
        """
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]

        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(memory_type.value)

        where = " AND ".join(clauses)
        params.append(limit)

        rows = await self._db.execute_fetchall(
            f"SELECT * FROM memory_items WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        )

        return [self._row_to_item(row) for row in rows]

    @staticmethod
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
