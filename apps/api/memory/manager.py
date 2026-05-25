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
from apps.api.models.memory_item import MemoryItem, MemoryStatus, MemoryType

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
                             confidence: float = 0.6, workspace_id: str = "default",
                             max_summaries: int = 1) -> MemoryItem:
        """Store a conversation summary.

        When the number of existing summaries reaches ``max_summaries``,
        the oldest ones are deleted to stay within the limit.
        """
        conn = await get_connection(self._db_path)
        try:
            if max_summaries >= 1:
                # Keep at most (max_summaries - 1) so the new one fits
                rows = await conn.execute_fetchall(
                    "SELECT id FROM memory_items "
                    "WHERE workspace_id = ? AND memory_type = 'summary' "
                    "ORDER BY created_at DESC",
                    (workspace_id,))
                ids_to_delete = [r["id"] for r in rows[max_summaries - 1:]]
                for old_id in ids_to_delete:
                    await conn.execute(
                        "DELETE FROM memory_items WHERE id = ?", (old_id,))
            await conn.commit()
        finally:
            await conn.close()
        return await self._store(MemoryType.SUMMARY, content, source, confidence, workspace_id)

    async def store_dream_insight(
        self,
        memory_type: MemoryType,
        content: str,
        confidence: float,
        workspace_id: str = "default",
    ) -> MemoryItem:
        """Store a dream-generated insight as ``pending_review``.

        Only ``strategy`` and ``preference`` types are accepted.
        """
        if memory_type not in (MemoryType.STRATEGY, MemoryType.PREFERENCE):
            raise ValueError(f"Dream insights must be strategy or preference, got {memory_type}")
        return await self._store(
            memory_type, content, "dream", confidence, workspace_id,
            status=MemoryStatus.PENDING_REVIEW,
        )

    async def review_insight(self, item_id: str, accepted: bool, edited_content: str | None = None) -> MemoryItem | None:
        """Accept or reject a pending dream insight.

        If ``accepted`` is True and ``edited_content`` is provided, the content
        is updated before promotion. Rejected items are marked so the dreamer
        won't re-propose them.
        """
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM memory_items WHERE id = ? AND status = 'pending_review'",
                (item_id,))
            if not rows:
                return None
            now = datetime.now(timezone.utc).isoformat()
            if accepted:
                new_content = edited_content if edited_content else rows[0]["content"]
                await conn.execute(
                    "UPDATE memory_items SET status = 'active', content = ?, updated_at = ? WHERE id = ?",
                    (new_content, now, item_id))
            else:
                await conn.execute(
                    "UPDATE memory_items SET status = 'rejected', updated_at = ? WHERE id = ?",
                    (now, item_id))
            await conn.commit()
            updated = await conn.execute_fetchall("SELECT * FROM memory_items WHERE id = ?", (item_id,))
            return self._row_to_item(updated[0]) if updated else None
        finally:
            await conn.close()

    async def get_pending_insights(self, workspace_id: str = "default") -> list[MemoryItem]:
        """Return all pending_review insights for user review."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM memory_items WHERE workspace_id = ? AND status = 'pending_review' "
                "ORDER BY created_at DESC",
                (workspace_id,))
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

    async def get_rejected_contents(self, workspace_id: str = "default") -> list[str]:
        """Return contents of rejected insights so the dreamer can avoid re-proposing."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT content FROM memory_items WHERE workspace_id = ? AND status = 'rejected'",
                (workspace_id,))
            return [r["content"] for r in rows]
        finally:
            await conn.close()

    async def count_active_by_type(self, workspace_id: str, memory_type: str) -> int:
        """Count active items of a given type (for FIFO cap enforcement)."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM memory_items "
                "WHERE workspace_id = ? AND memory_type = ? AND status = 'active'",
                (workspace_id, memory_type))
            return rows[0]["cnt"] if rows else 0
        finally:
            await conn.close()

    async def evict_lowest_confidence(self, workspace_id: str, memory_type: str) -> str | None:
        """Delete the active item with the lowest confidence for a given type.

        Returns the deleted item's ID, or None if nothing was evicted.
        Used by the dreamer for FIFO-with-reconfirmation cap enforcement.
        """
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT id FROM memory_items "
                "WHERE workspace_id = ? AND memory_type = ? AND status = 'active' "
                "ORDER BY confidence ASC, created_at ASC LIMIT 1",
                (workspace_id, memory_type))
            if not rows:
                return None
            evict_id = rows[0]["id"]
            await conn.execute("DELETE FROM memory_items WHERE id = ?", (evict_id,))
            await conn.commit()
            logger.info("Evicted lowest-confidence %s item %s", memory_type, evict_id)
            return evict_id
        finally:
            await conn.close()

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
                      workspace_id: str, summary: str | None = None, run_id: str | None = None,
                      status: MemoryStatus = MemoryStatus.ACTIVE) -> MemoryItem:
        item_id = f"mem_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        item = MemoryItem(id=item_id, workspace_id=workspace_id, memory_type=memory_type,
                           content=content, summary=summary, source=source, confidence=confidence,
                           visibility="user_visible", status=status,
                           created_at=now, updated_at=now, run_id=run_id)
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                """INSERT INTO memory_items (id, workspace_id, memory_type, content, summary, source,
                   confidence, visibility, status, created_at, updated_at, run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item.id, item.workspace_id, item.memory_type.value, item.content, item.summary,
                 item.source, item.confidence, item.visibility, item.status.value,
                 item.created_at, item.updated_at, item.run_id))
            await conn.commit()
            logger.info("Stored memory %s type=%s status=%s", item.id, item.memory_type.value, item.status.value)
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
        # Handle both old DBs (no status column) and new DBs
        status_val = row["status"] if "status" in row.keys() else "active"
        return MemoryItem(id=row["id"], workspace_id=row["workspace_id"], memory_type=row["memory_type"],
                           content=row["content"], summary=row["summary"], source=row["source"],
                           confidence=row["confidence"], visibility=row["visibility"],
                           status=status_val,
                           created_at=row["created_at"], updated_at=row["updated_at"], run_id=row["run_id"])
