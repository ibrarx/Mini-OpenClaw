"""
Tests for the memory subsystem.

Covers: MemoryManager CRUD, MemoryRetrieval search, context bundle,
export script, and edge cases.
"""

import json
from pathlib import Path

import pytest

from apps.api.database import create_tables, get_connection
from apps.api.memory.manager import MemoryManager
from apps.api.memory.retrieval import MemoryRetrieval
from apps.api.models.memory_item import MemoryType


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_db_path: Path) -> Path:
    """Return the tmp_db_path for convenience."""
    return tmp_db_path


# ── MemoryManager store/retrieve ──────────────────────────────────


@pytest.mark.asyncio
async def test_store_fact(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    item = await mm.store_fact(content="User prefers dark mode", source="user_input")
    assert item.id
    assert item.content == "User prefers dark mode"
    assert item.memory_type == MemoryType.FACT
    assert item.source == "user_input"
    assert item.confidence == 0.8  # default


@pytest.mark.asyncio
async def test_store_episode(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    item = await mm.store_episode(
        content="Listed files and found 5 items.",
        summary="Listed workspace files",
        source="run:run_123",
    )
    assert item.memory_type == MemoryType.EPISODE
    assert item.summary == "Listed workspace files"


@pytest.mark.asyncio
async def test_list_items(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    await mm.store_fact(content="Fact 1", source="test")
    await mm.store_fact(content="Fact 2", source="test")
    await mm.store_episode(content="Episode 1", summary="ep1", source="test")

    all_items = await mm.list_items()
    assert len(all_items) == 3

    facts_only = await mm.list_items(memory_type="fact")
    assert len(facts_only) == 2

    episodes_only = await mm.list_items(memory_type="episode")
    assert len(episodes_only) == 1


@pytest.mark.asyncio
async def test_delete_item(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    item = await mm.store_fact(content="Delete me", source="test")
    deleted = await mm.delete(item.id)
    assert deleted is True

    # Verify gone — list should be empty
    items = await mm.list_items()
    assert len(items) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    deleted = await mm.delete("nonexistent-id")
    assert deleted is False


# ── MemoryRetrieval ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_keyword(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    await mm.store_fact(content="User prefers dark mode", source="test")
    await mm.store_fact(content="Project uses Python 3.11", source="test")

    retrieval = MemoryRetrieval(db_path)
    results = await retrieval.search("dark mode")
    assert len(results) >= 1
    assert any("dark mode" in r.content for r in results)


@pytest.mark.asyncio
async def test_search_with_type_filter(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    await mm.store_fact(content="Python project", source="test")
    await mm.store_episode(content="Ran Python script", summary="ran script", source="test")

    retrieval = MemoryRetrieval(db_path)
    facts_only = await retrieval.search("Python", memory_type="fact")
    assert all(r.memory_type == MemoryType.FACT for r in facts_only)


@pytest.mark.asyncio
async def test_search_no_matches(db_path: Path) -> None:
    await create_tables(db_path)
    retrieval = MemoryRetrieval(db_path)
    results = await retrieval.search("nonexistent_xyz")
    assert results == []


@pytest.mark.asyncio
async def test_get_context_bundle(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    await mm.store_fact(content="User prefers dark mode", source="test")
    await mm.store_episode(content="Listed files", summary="listed", source="test")

    retrieval = MemoryRetrieval(db_path)
    context = await retrieval.get_context_bundle(query="dark mode")
    assert "dark mode" in context


@pytest.mark.asyncio
async def test_get_context_bundle_empty(db_path: Path) -> None:
    await create_tables(db_path)
    retrieval = MemoryRetrieval(db_path)
    context = await retrieval.get_context_bundle(query="anything")
    assert "No relevant" in context or context == ""


# ── Empty database edge cases ─────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_db_list(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    items = await mm.list_items()
    assert items == []


@pytest.mark.asyncio
async def test_empty_db_search(db_path: Path) -> None:
    await create_tables(db_path)
    retrieval = MemoryRetrieval(db_path)
    results = await retrieval.search("anything")
    assert results == []


# ── Export script ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_memory_produces_json(db_path: Path, tmp_path: Path) -> None:
    """Test the export_memory script produces valid JSON files."""
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    await mm.store_fact(content="Export test fact", source="test")
    await mm.store_episode(content="Export test episode", summary="ep", source="test")

    # Manually do what export_memory.py does
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    for mem_type in ("fact", "episode", "summary"):
        items = await mm.list_items(memory_type=mem_type, limit=10000)
        data = [i.model_dump() for i in items]
        out = export_dir / f"{mem_type}s.json"
        out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    assert (export_dir / "facts.json").exists()
    facts = json.loads((export_dir / "facts.json").read_text())
    assert len(facts) == 1
    assert facts[0]["content"] == "Export test fact"

    episodes = json.loads((export_dir / "episodes.json").read_text())
    assert len(episodes) == 1
