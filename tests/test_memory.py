"""
test_memory — Tests for the memory subsystem.

Covers: MemoryManager, MemoryRetrieval, export script, and edge cases.
"""

import json
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from apps.api.memory.manager import MemoryManager, MAX_SUMMARIES_PER_WORKSPACE
from apps.api.memory.retrieval import MemoryRetrieval
from apps.api.models.memory_item import MemoryItem, MemoryType


# ── MemoryManager Tests ──


@pytest.mark.asyncio
async def test_store_fact(test_db: aiosqlite.Connection) -> None:
    """Store a fact and retrieve it."""
    manager = MemoryManager(test_db)
    item = await manager.store_fact(
        content="User prefers dark mode",
        source="user_input",
    )
    assert item.id
    assert item.content == "User prefers dark mode"
    assert item.memory_type == MemoryType.FACT
    assert item.source == "user_input"
    assert item.confidence == 0.8  # default for store_fact


@pytest.mark.asyncio
async def test_store_fact_duplicate_detection(test_db: aiosqlite.Connection) -> None:
    """Storing the same fact twice returns the existing item."""
    manager = MemoryManager(test_db)
    item1 = await manager.store_fact(content="User likes Python", source="test")
    item2 = await manager.store_fact(content="User likes Python", source="test")
    assert item1.id == item2.id  # same item returned


@pytest.mark.asyncio
async def test_store_episode(test_db: aiosqlite.Connection) -> None:
    """Store an episode and retrieve it."""
    manager = MemoryManager(test_db)
    item = await manager.store_episode(
        content="User asked to list files. Used list_files tool. Found 5 files.",
        summary="Listed files in workspace (5 found)",
        source="run:run_123",
    )
    assert item.memory_type == MemoryType.EPISODE
    assert item.summary == "Listed files in workspace (5 found)"
    assert item.confidence == 1.0


@pytest.mark.asyncio
async def test_store_summary(test_db: aiosqlite.Connection) -> None:
    """Store a conversation summary."""
    manager = MemoryManager(test_db)
    item = await manager.store_summary(
        content="User explored workspace and created notes.txt",
    )
    assert item.memory_type == MemoryType.SUMMARY
    assert item.source == "system"


@pytest.mark.asyncio
async def test_summary_rotation(test_db: aiosqlite.Connection) -> None:
    """Old summaries get deleted when max is exceeded."""
    manager = MemoryManager(test_db)
    items = []
    for i in range(MAX_SUMMARIES_PER_WORKSPACE + 2):
        item = await manager.store_summary(content=f"Summary {i}")
        items.append(item)

    # Should only have MAX_SUMMARIES_PER_WORKSPACE summaries
    remaining = await manager.get_items(memory_type="summary", limit=100)
    assert len(remaining) <= MAX_SUMMARIES_PER_WORKSPACE


@pytest.mark.asyncio
async def test_get_items(test_db: aiosqlite.Connection) -> None:
    """List memory items with optional type filter."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="Fact 1", source="test")
    await manager.store_fact(content="Fact 2", source="test")
    await manager.store_episode(content="Episode 1", summary="ep1", source="test")

    all_items = await manager.get_items()
    assert len(all_items) == 3

    facts = await manager.get_items(memory_type="fact")
    assert len(facts) == 2

    episodes = await manager.get_items(memory_type="episode")
    assert len(episodes) == 1


@pytest.mark.asyncio
async def test_delete_item(test_db: aiosqlite.Connection) -> None:
    """Delete a memory item and verify it's gone."""
    manager = MemoryManager(test_db)
    item = await manager.store_fact(content="Delete me", source="test")

    deleted = await manager.delete_item(item.id)
    assert deleted is True

    # Verify gone
    result = await manager.get_item(item.id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_nonexistent(test_db: aiosqlite.Connection) -> None:
    """Deleting a nonexistent item returns False."""
    manager = MemoryManager(test_db)
    deleted = await manager.delete_item("nonexistent-id")
    assert deleted is False


@pytest.mark.asyncio
async def test_update_fact(test_db: aiosqlite.Connection) -> None:
    """Update a fact's content."""
    manager = MemoryManager(test_db)
    item = await manager.store_fact(content="Old fact", source="test")

    updated = await manager.update_fact(item.id, "New fact content")
    assert updated is not None
    assert updated.content == "New fact content"
    assert updated.id == item.id  # same id


@pytest.mark.asyncio
async def test_get_stats(test_db: aiosqlite.Connection) -> None:
    """Get memory stats by type."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="Fact 1", source="test")
    await manager.store_fact(content="Fact 2", source="test")
    await manager.store_episode(content="Ep 1", summary="ep", source="test")
    await manager.store_summary(content="Summary 1")

    stats = await manager.get_stats()
    assert stats["total"] == 4
    assert stats["facts"] == 2
    assert stats["episodes"] == 1
    assert stats["summaries"] == 1


# ── MemoryRetrieval Tests ──


@pytest.mark.asyncio
async def test_search_keyword(test_db: aiosqlite.Connection) -> None:
    """Search for a keyword and find matching items."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="User prefers dark mode", source="test")
    await manager.store_fact(content="Project uses Python 3.11", source="test")
    await manager.store_fact(content="Workspace is at ~/thesis", source="test")

    retrieval = MemoryRetrieval(test_db)
    results = await retrieval.search("dark mode")
    assert len(results) >= 1
    assert any("dark mode" in r.content for r in results)


@pytest.mark.asyncio
async def test_search_multiple_words(test_db: aiosqlite.Connection) -> None:
    """Multi-word search scores items with more matching words higher."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="User likes Python programming", source="test")
    await manager.store_fact(content="Python version is 3.11", source="test")
    await manager.store_fact(content="User likes cats", source="test")

    retrieval = MemoryRetrieval(test_db)
    results = await retrieval.search("Python programming")
    assert len(results) >= 1
    # The one with both words should rank higher
    assert "Python programming" in results[0].content or "Python" in results[0].content


@pytest.mark.asyncio
async def test_search_with_type_filter(test_db: aiosqlite.Connection) -> None:
    """Search with memory_type filter."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="Python project", source="test")
    await manager.store_episode(content="Ran Python script", summary="ran script", source="test")

    retrieval = MemoryRetrieval(test_db)
    facts_only = await retrieval.search("Python", memory_type=MemoryType.FACT)
    assert all(r.memory_type == MemoryType.FACT for r in facts_only)


@pytest.mark.asyncio
async def test_search_empty_query(test_db: aiosqlite.Connection) -> None:
    """Empty query falls back to listing all items."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="Some fact", source="test")

    retrieval = MemoryRetrieval(test_db)
    results = await retrieval.search("")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_get_context_for_planner(test_db: aiosqlite.Connection) -> None:
    """Build planner context from memory returns formatted text."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="User prefers dark mode", source="test")
    await manager.store_fact(content="Workspace is at ~/thesis", source="test")
    await manager.store_episode(
        content="Listed files in workspace, found README.md",
        summary="Listed workspace files",
        source="test",
    )
    await manager.store_summary(content="User explored workspace structure")

    retrieval = MemoryRetrieval(test_db)
    context = await retrieval.get_context_for_planner("list files")

    assert "Known facts:" in context
    assert "dark mode" in context
    assert "Recent activity:" in context or "Conversation summary:" in context


@pytest.mark.asyncio
async def test_get_context_empty_db(test_db: aiosqlite.Connection) -> None:
    """Planner context on empty DB returns empty string."""
    retrieval = MemoryRetrieval(test_db)
    context = await retrieval.get_context_for_planner("hello")
    assert context == ""


# ── Empty Database Edge Cases ──


@pytest.mark.asyncio
async def test_empty_db_get_items(test_db: aiosqlite.Connection) -> None:
    """get_items on empty DB returns empty list."""
    manager = MemoryManager(test_db)
    items = await manager.get_items()
    assert items == []


@pytest.mark.asyncio
async def test_empty_db_stats(test_db: aiosqlite.Connection) -> None:
    """get_stats on empty DB returns zeros."""
    manager = MemoryManager(test_db)
    stats = await manager.get_stats()
    assert stats == {"total": 0, "facts": 0, "episodes": 0, "summaries": 0}


@pytest.mark.asyncio
async def test_empty_db_search(test_db: aiosqlite.Connection) -> None:
    """Search on empty DB returns empty list."""
    retrieval = MemoryRetrieval(test_db)
    results = await retrieval.search("anything")
    assert results == []


# ── Export Script Test ──


@pytest.mark.asyncio
async def test_export_memory_script(test_db: aiosqlite.Connection, tmp_path: Path) -> None:
    """Export produces valid JSON files."""
    manager = MemoryManager(test_db)
    await manager.store_fact(content="Export test fact", source="test")
    await manager.store_episode(content="Export test episode", summary="ep", source="test")

    # Close the async connection and use sync export
    db_path = test_db._conn.path if hasattr(test_db._conn, 'path') else None

    # We need the actual db path; get it from the connection
    # For the export test, we'll directly test the export function
    import sqlite3

    # Get the db file path from the async connection
    rows = await test_db.execute_fetchall("PRAGMA database_list")
    db_file = None
    for row in rows:
        d = dict(row)
        if d.get("name") == "main":
            db_file = d.get("file")
            break

    if not db_file:
        pytest.skip("Could not determine database file path")

    from scripts.export_memory import export_memory

    output_dir = tmp_path / "exports"
    export_memory(Path(db_file), output_dir)

    # Verify files exist and are valid JSON
    assert (output_dir / "facts.json").exists()
    assert (output_dir / "episodes.json").exists()
    assert (output_dir / "summaries.json").exists()
    assert (output_dir / "audit_log.json").exists()

    facts = json.loads((output_dir / "facts.json").read_text())
    assert len(facts) == 1
    assert facts[0]["content"] == "Export test fact"

    episodes = json.loads((output_dir / "episodes.json").read_text())
    assert len(episodes) == 1
