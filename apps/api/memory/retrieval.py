"""
Memory retrieval — search and retrieve memory context.

Minimal V1 implementation using SQLite LIKE for keyword matching.
Full expansion with FTS5 in T05.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

from ..models.memory_item import MemoryItem, MemoryType, MemoryVisibility

logger = logging.getLogger(__name__)


class MemoryRetrieval:
    """Search and retrieve memory items from SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def search(
        self,
        query: str,
        memory_type: str | None = None,
        workspace_id: str = "default",
        limit: int = 10,
    ) -> list[MemoryItem]:
        """
        Search memory items by keyword match.

        Args:
            query: Search keywords.
            memory_type: Optional filter (fact, episode, summary).
            workspace_id: Workspace scope.
            limit: Maximum results.

        Returns:
            List of matching MemoryItem records.
        """
        conditions = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]

        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")

        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)

        where = " AND ".join(conditions)
        params.append(limit)

        async with aiosqlite.connect(str(self.db_path)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                f"""
                SELECT * FROM memory_items
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()

        items: list[MemoryItem] = []
        for row in rows:
            items.append(
                MemoryItem(
                    id=row["id"],
                    workspace_id=row["workspace_id"],
                    memory_type=MemoryType(row["memory_type"]),
                    content=row["content"],
                    summary=row["summary"],
                    source=row["source"],
                    confidence=row["confidence"],
                    visibility=MemoryVisibility(row["visibility"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    run_id=row["run_id"],
                )
            )

        return items
