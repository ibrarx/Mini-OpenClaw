"""
Memory retrieval — search and retrieve memory context.

Provides keyword search over SQLite for V1 with word-level scoring.
Semantic/embedding retrieval is a stretch goal.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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
        """Search memory items by keyword with word-level scoring.

        Implementation:
        1. Split query into words
        2. Search for each word using LIKE
        3. Score by: number of matching words + recency + confidence
        4. Filter by workspace and optional type
        5. Return top-k results sorted by score

        Args:
            query: Search keywords.
            workspace_id: Scope to a specific workspace.
            memory_type: Optionally filter by memory category.
            limit: Maximum results to return.

        Returns:
            List of matching MemoryItem objects ranked by relevance.
        """
        if not query or not query.strip():
            return await self.list_items(
                workspace_id=workspace_id,
                memory_type=memory_type,
                limit=limit,
            )

        words = [w.lower() for w in query.strip().split() if len(w) >= 2]
        if not words:
            return await self.list_items(
                workspace_id=workspace_id,
                memory_type=memory_type,
                limit=limit,
            )

        # Build params list in exact SQL placeholder order:
        # 1. Score expression CASE WHEN params
        # 2. WHERE clause params (workspace_id, then OR-match params, then optional type)
        # 3. LIMIT
        all_params: list[Any] = []

        # ── SELECT: score expression ──
        score_parts: list[str] = []
        for word in words:
            score_parts.append(
                "(CASE WHEN LOWER(content) LIKE ? THEN 1 ELSE 0 END + "
                "CASE WHEN LOWER(COALESCE(summary, '')) LIKE ? THEN 1 ELSE 0 END)"
            )
            like = f"%{word}%"
            all_params.extend([like, like])

        score_expr = " + ".join(score_parts)

        # ── WHERE ──
        # workspace_id comes first in WHERE
        where_parts = ["workspace_id = ?"]
        all_params.append(workspace_id)

        # At least one word must match
        or_clauses = []
        for word in words:
            or_clauses.append(
                "(LOWER(content) LIKE ? OR LOWER(COALESCE(summary, '')) LIKE ?)"
            )
            like = f"%{word}%"
            all_params.extend([like, like])
        where_parts.append(f"({' OR '.join(or_clauses)})")

        if memory_type is not None:
            where_parts.append("memory_type = ?")
            all_params.append(memory_type.value)

        where = " AND ".join(where_parts)

        # LIMIT
        all_params.append(limit)

        sql = f"""
            SELECT *,
                   ({score_expr}) AS match_score
            FROM memory_items
            WHERE {where}
            ORDER BY match_score DESC, updated_at DESC, confidence DESC
            LIMIT ?
        """

        rows = await self._db.execute_fetchall(sql, all_params)
        return [_row_to_item(row) for row in rows]

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
        return [_row_to_item(row) for row in rows]

    async def get_context_for_planner(
        self,
        message: str,
        workspace_id: str = "default",
        max_items: int = 10,
    ) -> str:
        """Build a context string for injection into the planner prompt.

        Combines:
        1. Recent facts (top 5 by recency)
        2. Relevant past episodes matching keywords from the message (top 3)
        3. Most recent conversation summary (if exists)

        Args:
            message: The user's current message (for keyword extraction).
            workspace_id: Logical workspace scope.
            max_items: Maximum total items to include.

        Returns:
            Formatted context string for the planner, or empty string
            if no relevant memory is found.
        """
        parts: list[str] = []

        # 1. Recent facts
        facts = await self.list_items(
            workspace_id=workspace_id,
            memory_type=MemoryType.FACT,
            limit=5,
        )
        if facts:
            fact_lines = [f"- {f.content}" for f in facts]
            parts.append("Known facts:\n" + "\n".join(fact_lines))

        # 2. Relevant episodes (search by message keywords)
        episodes = await self.search(
            query=message,
            workspace_id=workspace_id,
            memory_type=MemoryType.EPISODE,
            limit=3,
        )
        if episodes:
            ep_lines = []
            for ep in episodes:
                display = ep.summary if ep.summary else ep.content[:100]
                time_info = _relative_time(ep.created_at)
                ep_lines.append(f"- {display} ({time_info})")
            parts.append("Recent activity:\n" + "\n".join(ep_lines))

        # 3. Most recent summary
        summaries = await self.list_items(
            workspace_id=workspace_id,
            memory_type=MemoryType.SUMMARY,
            limit=1,
        )
        if summaries:
            parts.append(f"Conversation summary:\n{summaries[0].content}")

        return "\n\n".join(parts)


def _relative_time(iso_str: str) -> str:
    """Convert an ISO timestamp to a human-friendly relative time string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = delta.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(seconds / 86400)
            if days == 1:
                return "yesterday"
            return f"{days} days ago"
    except (ValueError, TypeError):
        return "unknown time"


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
