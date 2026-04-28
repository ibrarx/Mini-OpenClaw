"""memory/retrieval — Search and retrieve memory context."""
from __future__ import annotations
import logging
from pathlib import Path
import aiosqlite
from apps.api.database import get_connection
from apps.api.models.memory_item import MemoryItem

logger = logging.getLogger(__name__)


class MemoryRetrieval:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def search(self, query: str, workspace_id: str = "default",
                      memory_type: str | None = None, limit: int = 10) -> list[MemoryItem]:
        conn = await get_connection(self._db_path)
        try:
            keywords = [kw.strip() for kw in query.split() if kw.strip()]
            if not keywords:
                return []
            conditions = ["workspace_id = ?"]
            params: list = [workspace_id]
            if memory_type:
                conditions.append("memory_type = ?")
                params.append(memory_type)
            kw_clauses = []
            for kw in keywords:
                kw_clauses.append("(content LIKE ? OR summary LIKE ?)")
                params.extend([f"%{kw}%", f"%{kw}%"])
            if kw_clauses:
                conditions.append(f"({' OR '.join(kw_clauses)})")
            where = " AND ".join(conditions)
            params.append(limit)
            rows = await conn.execute_fetchall(
                f"SELECT * FROM memory_items WHERE {where} ORDER BY confidence DESC, created_at DESC LIMIT ?",
                tuple(params))
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

    async def get_context_bundle(self, query: str, workspace_id: str = "default", limit: int = 5) -> str:
        items = await self.search(query=query, workspace_id=workspace_id, limit=limit)
        if not items:
            return "No relevant memories found."
        lines = ["Relevant memories:"]
        for item in items:
            lines.append(f"- [{item.memory_type.value}] {item.content} (confidence={item.confidence:.1f})")
        return "\n".join(lines)

    @staticmethod
    def _row_to_item(row: aiosqlite.Row) -> MemoryItem:
        return MemoryItem(id=row["id"], workspace_id=row["workspace_id"], memory_type=row["memory_type"],
                           content=row["content"], summary=row["summary"], source=row["source"],
                           confidence=row["confidence"], visibility=row["visibility"],
                           created_at=row["created_at"], updated_at=row["updated_at"], run_id=row["run_id"])
