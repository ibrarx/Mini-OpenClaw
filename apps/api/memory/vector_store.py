"""
memory/vector_store — SQLite-based vector storage with cosine similarity search.

Stores embeddings alongside memory items. Uses brute-force cosine similarity
in numpy for search (fine for <10K items). Content hashing avoids re-embedding
unchanged items.

Table: memory_vectors
  - item_id TEXT PRIMARY KEY (references memory_items.id)
  - embedding BLOB (stored as JSON array of floats)
  - content_hash TEXT (SHA-256 of the text that was embedded)
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import aiosqlite

from apps.api.database import get_connection

logger = logging.getLogger(__name__)

CREATE_VECTORS_TABLE = """
CREATE TABLE IF NOT EXISTS memory_vectors (
    item_id      TEXT PRIMARY KEY,
    embedding    TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
"""


def _content_hash(text: str) -> str:
    """SHA-256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VectorStore:
    """SQLite-backed vector storage with brute-force cosine similarity."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def ensure_table(self) -> None:
        """Create the memory_vectors table if it doesn't exist."""
        conn = await get_connection(self._db_path)
        try:
            await conn.executescript(CREATE_VECTORS_TABLE)
            await conn.commit()
        finally:
            await conn.close()

    async def upsert(self, item_id: str, text: str, embedding: list[float]) -> None:
        """Store embedding. Skip if content_hash matches (text unchanged)."""
        new_hash = _content_hash(text)
        conn = await get_connection(self._db_path)
        try:
            # Check if already stored with same content
            rows = await conn.execute_fetchall(
                "SELECT content_hash FROM memory_vectors WHERE item_id = ?",
                (item_id,),
            )
            if rows and rows[0]["content_hash"] == new_hash:
                return  # Content unchanged, skip

            embedding_json = json.dumps(embedding)
            await conn.execute(
                """INSERT INTO memory_vectors (item_id, embedding, content_hash)
                   VALUES (?, ?, ?)
                   ON CONFLICT(item_id) DO UPDATE SET
                     embedding = excluded.embedding,
                     content_hash = excluded.content_hash""",
                (item_id, embedding_json, new_hash),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def delete(self, item_id: str) -> None:
        """Remove an embedding when a memory item is deleted."""
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                "DELETE FROM memory_vectors WHERE item_id = ?", (item_id,)
            )
            await conn.commit()
        finally:
            await conn.close()

    async def search(
        self, query_embedding: list[float], limit: int = 10
    ) -> list[tuple[str, float]]:
        """Return (item_id, cosine_similarity) pairs sorted by similarity DESC.

        Uses brute-force numpy computation — fine for <10K items.
        """
        try:
            import numpy as np
        except ImportError:
            logger.warning("numpy not installed; vector search unavailable")
            return []

        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT item_id, embedding FROM memory_vectors"
            )
            if not rows:
                return []

            # Parse embeddings
            item_ids = []
            embeddings = []
            for row in rows:
                try:
                    emb = json.loads(row["embedding"])
                    item_ids.append(row["item_id"])
                    embeddings.append(emb)
                except (json.JSONDecodeError, TypeError):
                    continue

            if not embeddings:
                return []

            # Compute cosine similarities
            query_vec = np.array(query_embedding, dtype=np.float32)
            matrix = np.array(embeddings, dtype=np.float32)

            # Normalize
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return []
            query_vec = query_vec / query_norm

            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)  # avoid div by zero
            matrix = matrix / norms

            # Cosine similarity = dot product of normalized vectors
            similarities = matrix @ query_vec

            # Sort by similarity descending, take top limit
            indices = np.argsort(similarities)[::-1][:limit]
            results = [
                (item_ids[i], float(similarities[i]))
                for i in indices
                if similarities[i] > 0
            ]
            return results
        finally:
            await conn.close()

    async def count(self) -> int:
        """Return number of stored vectors."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM memory_vectors"
            )
            return rows[0]["cnt"] if rows else 0
        except Exception:
            return 0
        finally:
            await conn.close()

    async def get_indexed_ids(self) -> set[str]:
        """Return set of all item_ids that have embeddings."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT item_id FROM memory_vectors"
            )
            return {row["item_id"] for row in rows}
        except Exception:
            return set()
        finally:
            await conn.close()
