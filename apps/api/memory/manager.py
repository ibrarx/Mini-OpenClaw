"""memory/manager — Write, update, and delete memory items."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
import aiosqlite
from apps.api.database import get_connection
from apps.api.models.memory_item import MemoryItem, MemoryType

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def store_fact(self, content: str, source: str = "user", confidence: float = 0.8,
                          workspace_id: str = "default", run_id: str | None = None) -> MemoryItem:
        return await self._store(MemoryType.FACT, content, source, confidence, workspace_id, run_id=run_id)

    async def store_episode(self, content: str, summary: str | None = None, source: str = "system",
                             confidence: float = 0.7, workspace_id: str = "default",
                             run_id: str | None = None) -> MemoryItem:
        return await self._store(MemoryType.EPISODE, content, source, confidence, workspace_id,
                                  summary=summary, run_id=run_id)

    async def _store(self, memory_type: MemoryType, content: str, source: str, confidence: float,
                      workspace_id: str, summary: str | None = None, run_id: str | None = None) -> MemoryItem:
        item_id = f"mem_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        item = MemoryItem(id=item_id, workspace_id=workspace_id, memory_type=memory_type,
                           content=content, summary=summary, source=source, confidence=confidence,
                           visibility="user_visible", created_at=now, updated_at=now, run_id=run_id)
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                """INSERT INTO memory_items (id, workspace_id, memory_type, content, summary, source,
                   confidence, visibility, created_at, updated_at, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (item.id, item.workspace_id, item.memory_type.value, item.content, item.summary,
                 item.source, item.confidence, item.visibility, item.created_at, item.updated_at, item.run_id))
            await conn.commit()
            logger.info("Stored memory %s type=%s", item.id, item.memory_type.value)
        finally:
            await conn.close()
        return item

    async def delete(self, item_id: str) -> bool:
        conn = await get_connection(self._db_path)
        try:
            cursor = await conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()

    async def list_items(self, workspace_id: str = "default", memory_type: str | None = None,
                          limit: int = 100) -> list[MemoryItem]:
        conn = await get_connection(self._db_path)
        try:
            if memory_type:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM memory_items WHERE workspace_id = ? AND memory_type = ? ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, memory_type, limit))
            else:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM memory_items WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, limit))
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

    @staticmethod
    def _row_to_item(row: dict) -> MemoryItem:
        return MemoryItem(id=row["id"], workspace_id=row["workspace_id"], memory_type=row["memory_type"],
                           content=row["content"], summary=row["summary"], source=row["source"],
                           confidence=row["confidence"], visibility=row["visibility"],
                           created_at=row["created_at"], updated_at=row["updated_at"], run_id=row["run_id"])
