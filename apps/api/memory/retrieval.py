"""
memory/retrieval — Hybrid search (semantic + keyword) and context building.

Combines vector similarity (70% weight) with keyword matching (30% weight)
for more robust memory search. Falls back to keyword-only if embeddings
are unavailable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from apps.api.database import get_connection
from apps.api.memory.embeddings import EmbeddingProvider
from apps.api.memory.vector_store import VectorStore
from apps.api.models.memory_item import MemoryItem, MemoryType

logger = logging.getLogger(__name__)

# Hybrid search weights (match OpenClaw design)
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


class MemoryRetrieval:
    """Hybrid memory search: semantic embeddings + keyword matching."""

    def __init__(
        self,
        db_path: Path,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._db_path = db_path
        self._embedder = embedding_provider
        self._vectors = vector_store

    # ------------------------------------------------------------------
    # Core search methods
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        workspace_id: str = "default",
        memory_type: str | None = None,
        limit: int = 10,
        search_mode: str = "hybrid",
    ) -> list[MemoryItem]:
        """Hybrid search combining vector similarity and keyword matching.

        Parameters
        ----------
        search_mode : str
            "hybrid" (default), "keyword", or "vector"
        """
        if search_mode == "keyword" or not self._can_do_vector_search():
            return await self._keyword_search(
                query, workspace_id, memory_type, limit
            )

        if search_mode == "vector":
            return await self._vector_search(
                query, workspace_id, memory_type, limit
            )

        # Hybrid: merge vector + keyword results
        candidate_pool = limit * 4

        # 1. Vector search
        vector_results = await self._vector_search_scored(
            query, workspace_id, memory_type, candidate_pool
        )

        # 2. Keyword search
        keyword_results = await self._keyword_search_scored(
            query, workspace_id, memory_type, candidate_pool
        )

        # 3. Merge with weights
        merged = self._merge_results(vector_results, keyword_results, limit)
        return merged

    async def search_with_scores(
        self,
        query: str,
        workspace_id: str = "default",
        memory_type: str | None = None,
        limit: int = 10,
        search_mode: str = "hybrid",
    ) -> list[tuple[MemoryItem, float]]:
        """Like search() but returns (item, score) tuples."""
        if search_mode == "keyword" or not self._can_do_vector_search():
            scored = await self._keyword_search_scored(
                query, workspace_id, memory_type, limit
            )
            return [(item, score) for item, score in scored]

        if search_mode == "vector":
            scored = await self._vector_search_scored(
                query, workspace_id, memory_type, limit
            )
            return [(item, score) for item, score in scored]

        # Hybrid
        candidate_pool = limit * 4
        vector_results = await self._vector_search_scored(
            query, workspace_id, memory_type, candidate_pool
        )
        keyword_results = await self._keyword_search_scored(
            query, workspace_id, memory_type, candidate_pool
        )
        return self._merge_results_with_scores(
            vector_results, keyword_results, limit
        )

    # ------------------------------------------------------------------
    # Context building for planner injection
    # ------------------------------------------------------------------

    async def get_context_for_planner(
        self,
        message: str,
        workspace_id: str = "default",
        max_items: int = 10,
    ) -> str:
        """Build a rich context string for injection into the planner prompt.

        1. ALL stored facts (they're small and always relevant)
        2. Top relevant episodes via hybrid search
        3. Most recent conversation summary if exists
        """
        sections: list[str] = []

        # 1. All facts
        facts = await self._get_all_items(workspace_id, "fact")
        if facts:
            fact_lines = [f"- {f.content}" for f in facts]
            sections.append(
                "## Known Facts About User\n" + "\n".join(fact_lines)
            )

        # 2. Relevant episodes via hybrid search
        episodes = await self.search(
            query=message,
            workspace_id=workspace_id,
            memory_type="episode",
            limit=min(5, max_items),
            search_mode="hybrid",
        )
        if episodes:
            ep_lines = []
            for ep in episodes:
                ts = ep.created_at[:16] if ep.created_at else "unknown"
                text = ep.summary or ep.content
                # Truncate long content
                if len(text) > 200:
                    text = text[:200] + "..."
                ep_lines.append(f"- [{ts}] {text}")
            sections.append(
                "## Relevant Past Context\n" + "\n".join(ep_lines)
            )

        # 3. Most recent summary
        summaries = await self._get_all_items(workspace_id, "summary", limit=1)
        if summaries:
            sections.append(
                "## Conversation Summary\n" + summaries[0].content
            )

        if not sections:
            return "No relevant memories found."

        return "\n\n".join(sections)

    # Backward-compatible alias
    async def get_context_bundle(
        self,
        query: str,
        workspace_id: str = "default",
        limit: int = 5,
    ) -> str:
        """Backward-compatible alias for get_context_for_planner."""
        return await self.get_context_for_planner(
            message=query, workspace_id=workspace_id, max_items=limit
        )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_item(self, item: MemoryItem) -> bool:
        """Embed a memory item and store in vector index. Returns True on success."""
        if not self._can_do_vector_search():
            return False
        try:
            embedding = await self._embedder.embed(item.content)
            if embedding is None:
                return False
            await self._vectors.upsert(item.id, item.content, embedding)
            return True
        except Exception as exc:
            logger.warning("Failed to index memory item %s: %s", item.id, exc)
            return False

    async def reindex_all(self, workspace_id: str = "default") -> int:
        """Batch re-embed all memory items missing from the vector store.

        Returns count of newly indexed items.
        """
        if not self._can_do_vector_search():
            return 0

        # Get all memory items
        all_items = await self._get_all_items(workspace_id, memory_type=None)
        if not all_items:
            return 0

        # Get already-indexed IDs
        indexed_ids = await self._vectors.get_indexed_ids()

        # Filter to un-indexed items
        to_index = [item for item in all_items if item.id not in indexed_ids]
        if not to_index:
            return 0

        # Batch embed
        texts = [item.content for item in to_index]
        embeddings = await self._embedder.embed_batch(texts)
        if embeddings is None:
            return 0

        count = 0
        for item, embedding in zip(to_index, embeddings):
            if embedding is not None:
                try:
                    await self._vectors.upsert(item.id, item.content, embedding)
                    count += 1
                except Exception as exc:
                    logger.warning("Failed to index %s: %s", item.id, exc)

        logger.info("Reindexed %d/%d memory items", count, len(to_index))
        return count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _can_do_vector_search(self) -> bool:
        """Check if vector search is available."""
        return (
            self._embedder is not None
            and self._embedder.available
            and self._vectors is not None
        )

    async def _keyword_search(
        self,
        query: str,
        workspace_id: str,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryItem]:
        """Original keyword-based search using LIKE."""
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
                f"SELECT * FROM memory_items WHERE {where} "
                f"ORDER BY confidence DESC, created_at DESC LIMIT ?",
                tuple(params),
            )
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

    async def _keyword_search_scored(
        self,
        query: str,
        workspace_id: str,
        memory_type: str | None,
        limit: int,
    ) -> list[tuple[MemoryItem, float]]:
        """Keyword search returning (item, score) tuples.

        Score is a simple overlap ratio: matching keywords / total keywords.
        """
        items = await self._keyword_search(query, workspace_id, memory_type, limit)
        keywords = {kw.lower() for kw in query.split() if kw.strip()}
        if not keywords:
            return [(item, 0.0) for item in items]

        scored = []
        for item in items:
            content_lower = (item.content + " " + (item.summary or "")).lower()
            matches = sum(1 for kw in keywords if kw in content_lower)
            score = matches / len(keywords) if keywords else 0.0
            scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def _vector_search(
        self,
        query: str,
        workspace_id: str,
        memory_type: str | None,
        limit: int,
    ) -> list[MemoryItem]:
        """Vector-only search."""
        scored = await self._vector_search_scored(
            query, workspace_id, memory_type, limit
        )
        return [item for item, _ in scored]

    async def _vector_search_scored(
        self,
        query: str,
        workspace_id: str,
        memory_type: str | None,
        limit: int,
    ) -> list[tuple[MemoryItem, float]]:
        """Vector search returning (item, similarity) tuples."""
        if not self._can_do_vector_search():
            return []

        query_embedding = await self._embedder.embed(query)
        if query_embedding is None:
            return []

        # Get more candidates than needed to filter by workspace/type
        candidates = await self._vectors.search(
            query_embedding, limit=limit * 3
        )
        if not candidates:
            return []

        # Fetch full items and filter
        item_ids = [cid for cid, _ in candidates]
        score_map = {cid: score for cid, score in candidates}

        items = await self._get_items_by_ids(item_ids)
        results = []
        for item in items:
            if item.workspace_id != workspace_id:
                continue
            if memory_type and item.memory_type.value != memory_type:
                continue
            results.append((item, score_map.get(item.id, 0.0)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def _merge_results(
        self,
        vector_results: list[tuple[MemoryItem, float]],
        keyword_results: list[tuple[MemoryItem, float]],
        limit: int,
    ) -> list[MemoryItem]:
        """Merge vector + keyword results by weighted score."""
        merged = self._merge_results_with_scores(
            vector_results, keyword_results, limit
        )
        return [item for item, _ in merged]

    def _merge_results_with_scores(
        self,
        vector_results: list[tuple[MemoryItem, float]],
        keyword_results: list[tuple[MemoryItem, float]],
        limit: int,
    ) -> list[tuple[MemoryItem, float]]:
        """Merge vector + keyword results with weighted scoring.

        final_score = VECTOR_WEIGHT * vector_score + KEYWORD_WEIGHT * keyword_score
        """
        vec_scores: dict[str, float] = {}
        vec_items: dict[str, MemoryItem] = {}
        for item, score in vector_results:
            vec_scores[item.id] = score
            vec_items[item.id] = item

        kw_scores: dict[str, float] = {}
        kw_items: dict[str, MemoryItem] = {}
        for item, score in keyword_results:
            kw_scores[item.id] = score
            kw_items[item.id] = item

        all_ids = set(vec_scores.keys()) | set(kw_scores.keys())
        all_items = {**vec_items, **kw_items}

        scored: list[tuple[MemoryItem, float]] = []
        for item_id in all_ids:
            vs = vec_scores.get(item_id, 0.0)
            ks = kw_scores.get(item_id, 0.0)
            final = VECTOR_WEIGHT * vs + KEYWORD_WEIGHT * ks
            scored.append((all_items[item_id], final))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def _get_all_items(
        self,
        workspace_id: str,
        memory_type: str | None,
        limit: int = 1000,
    ) -> list[MemoryItem]:
        """Fetch all memory items, optionally filtered by type."""
        conn = await get_connection(self._db_path)
        try:
            if memory_type:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM memory_items "
                    "WHERE workspace_id = ? AND memory_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, memory_type, limit),
                )
            else:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM memory_items "
                    "WHERE workspace_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, limit),
                )
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

    async def _get_items_by_ids(self, item_ids: list[str]) -> list[MemoryItem]:
        """Fetch multiple memory items by their IDs."""
        if not item_ids:
            return []
        conn = await get_connection(self._db_path)
        try:
            placeholders = ",".join("?" for _ in item_ids)
            rows = await conn.execute_fetchall(
                f"SELECT * FROM memory_items WHERE id IN ({placeholders})",
                tuple(item_ids),
            )
            return [self._row_to_item(row) for row in rows]
        finally:
            await conn.close()

    @staticmethod
    def _row_to_item(row: aiosqlite.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            workspace_id=row["workspace_id"],
            memory_type=row["memory_type"],
            content=row["content"],
            summary=row["summary"],
            source=row["source"],
            confidence=row["confidence"],
            visibility=row["visibility"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            run_id=row["run_id"],
        )
