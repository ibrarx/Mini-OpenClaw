"""memory/manager — Write, update, and delete memory items.

Auto-indexes new items into the vector store for semantic search
when an embedding provider and vector store are available.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
import aiosqlite
from apps.api.database import get_connection
from apps.api.models.memory_item import MemoryItem, MemoryType

if TYPE_CHECKING:
    from apps.api.memory.embeddings import EmbeddingProvider
    from apps.api.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(
        self,
        db_path: Path,
        embedding_provider: "EmbeddingProvider | None" = None,
        vector_store: "VectorStore | None" = None,
    ) -> None:
        self._db_path = db_path
        self._embedder = embedding_provider
        self._vectors = vector_store

    async def store_fact(self, content: str, source: str = "user", confidence: float = 0.8,
                          workspace_id: str = "default", run_id: str | None = None) -> MemoryItem:
        return await self._store(MemoryType.FACT, content, source, confidence, workspace_id, run_id=run_id)

    async def store_episode(self, content: str, summary: str | None = None, source: str = "system",
                             confidence: float = 0.7, workspace_id: str = "default",
                             run_id: str | None = None) -> MemoryItem:
        return await self._store(MemoryType.EPISODE, content, source, confidence, workspace_id,
                                  summary=summary, run_id=run_id)

    async def store_summary(self, content: str, source: str = "system",
                             confidence: float = 0.6, workspace_id: str = "default") -> MemoryItem:
        """Store a conversation summary. Replaces previous summaries to keep one current."""
        # Delete older summaries (keep only the latest)
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                "DELETE FROM memory_items WHERE workspace_id = ? AND memory_type = 'summary'",
                (workspace_id,))
            await conn.commit()
        finally:
            await conn.close()
        return await self._store(MemoryType.SUMMARY, content, source, confidence, workspace_id)

    async def episode_count(self, workspace_id: str = "default") -> int:
        """Count episodes in the workspace (used to decide when to generate summaries)."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM memory_items WHERE workspace_id = ? AND memory_type = 'episode'",
                (workspace_id,))
            return rows[0]["cnt"] if rows else 0
        finally:
            await conn.close()

    async def get_recent_episodes(self, workspace_id: str = "default",
                                    limit: int = 10) -> list[MemoryItem]:
        """Get the most recent episodes for summarization."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM memory_items WHERE workspace_id = ? AND memory_type = 'episode' "
                "ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit))
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

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
        # Auto-index into vector store for semantic search
        await self._index_item(item)
        return item

    async def _index_item(self, item: MemoryItem) -> None:
        """Embed and index a memory item if embedding provider is available."""
        if self._embedder is None or self._vectors is None:
            return
        if not self._embedder.available:
            return
        try:
            embedding = await self._embedder.embed(item.content)
            if embedding is not None:
                await self._vectors.upsert(item.id, item.content, embedding)
                logger.debug("Indexed memory item %s in vector store", item.id)
        except Exception as exc:
            logger.warning("Failed to index memory item %s: %s", item.id, exc)

    async def delete(self, item_id: str) -> bool:
        conn = await get_connection(self._db_path)
        try:
            cursor = await conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()

    async def soft_delete_by_run(self, run_id: str) -> int:
        """Soft-delete all memory items created by a given run (saga compensation)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = await get_connection(self._db_path)
        try:
            cursor = await conn.execute(
                "DELETE FROM memory_items WHERE run_id = ?", (run_id,))
            await conn.commit()
            deleted = cursor.rowcount
            logger.info("Soft-deleted %d memory items for run %s", deleted, run_id)
            return deleted
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
    def _row_to_item(row: aiosqlite.Row) -> MemoryItem:
        return MemoryItem(id=row["id"], workspace_id=row["workspace_id"], memory_type=row["memory_type"],
                           content=row["content"], summary=row["summary"], source=row["source"],
                           confidence=row["confidence"], visibility=row["visibility"],
                           created_at=row["created_at"], updated_at=row["updated_at"], run_id=row["run_id"])
