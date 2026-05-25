"""
Tests for the Agent Dreams memory consolidation system.

Covers:
  - Dreamer produces strategies and preferences from episodes
  - Dream skips when fewer than 3 episodes
  - Confidence threshold filtering (below 0.6 → not stored)
  - Duplicate avoidance (existing + rejected passed to LLM)
  - Pending review lifecycle (store → review → accept/reject)
  - FIFO eviction at cap
  - _maybe_dream interval logic
  - Strategies and preferences appear in planner context only when active
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from apps.api.config import Settings
from apps.api.database import create_tables
from apps.api.memory.dreamer import Dreamer
from apps.api.memory.manager import MemoryManager
from apps.api.memory.retrieval import MemoryRetrieval
from apps.api.models.memory_item import MemoryStatus, MemoryType
from apps.api.providers.base import LLMProvider, LLMMessage, LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_db_path: Path) -> Path:
    return tmp_db_path


class FakeLLMProvider(LLMProvider):
    """Fake provider that returns pre-configured JSON responses."""

    name = "fake"

    def __init__(self, json_response: dict | None = None) -> None:
        self._json_response = json_response or {"strategies": [], "preferences": []}

    def set_response(self, response: dict) -> None:
        self._json_response = response

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools=None,
        max_tokens: int = 2048,
        temperature: float | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        return LLMResponse(text=json.dumps(self._json_response))


@pytest.fixture
def fake_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


async def _seed_episodes(mm: MemoryManager, count: int, workspace_id: str = "default") -> None:
    """Seed the database with N dummy episodes."""
    for i in range(count):
        await mm.store_episode(
            content=f"User asked: task {i}. Tools used: list_files. Result: completed.",
            summary=f"task {i} → list_files → done",
            source=f"run:run_{i:03d}",
            workspace_id=workspace_id,
        )


# ── Dreamer core ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dream_produces_strategies_and_preferences(db_path: Path, fake_provider: FakeLLMProvider) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    await _seed_episodes(mm, 5)

    fake_provider.set_response({
        "strategies": [
            {"content": "User always lists files before reading them", "confidence": 0.85},
        ],
        "preferences": [
            {"content": "User's project uses Python with pytest", "confidence": 0.78},
        ],
    })

    dreamer = Dreamer(fake_provider, mm, retrieval)
    result = await dreamer.dream()

    assert result["strategies"] == 1
    assert result["preferences"] == 1

    # Verify they're stored as pending_review
    pending = await mm.get_pending_insights()
    assert len(pending) == 2
    assert all(p.status == MemoryStatus.PENDING_REVIEW for p in pending)

    types = {p.memory_type for p in pending}
    assert MemoryType.STRATEGY in types
    assert MemoryType.PREFERENCE in types


@pytest.mark.asyncio
async def test_dream_skips_when_not_enough_episodes(db_path: Path, fake_provider: FakeLLMProvider) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    await _seed_episodes(mm, 2)  # Only 2, need at least 3

    dreamer = Dreamer(fake_provider, mm, retrieval)
    result = await dreamer.dream()

    assert result["strategies"] == 0
    assert result["preferences"] == 0
    assert "skipped" in result
    assert "not enough episodes" in result["skipped"]


@pytest.mark.asyncio
async def test_dream_filters_by_confidence_threshold(db_path: Path, fake_provider: FakeLLMProvider) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    await _seed_episodes(mm, 5)

    fake_provider.set_response({
        "strategies": [
            {"content": "High confidence", "confidence": 0.9},
            {"content": "Low confidence", "confidence": 0.3},  # Below 0.6 threshold
            {"content": "Borderline", "confidence": 0.6},       # Exactly at threshold
        ],
        "preferences": [
            {"content": "Too low", "confidence": 0.1},
        ],
    })

    dreamer = Dreamer(fake_provider, mm, retrieval, confidence_threshold=0.6)
    result = await dreamer.dream()

    assert result["strategies"] == 2  # High + Borderline pass
    assert result["preferences"] == 0  # Too low filtered out

    pending = await mm.get_pending_insights()
    contents = {p.content for p in pending}
    assert "High confidence" in contents
    assert "Borderline" in contents
    assert "Low confidence" not in contents
    assert "Too low" not in contents


@pytest.mark.asyncio
async def test_dream_passes_existing_and_rejected_to_llm(db_path: Path, fake_provider: FakeLLMProvider) -> None:
    """Verify the dreamer includes existing, pending, and rejected items in its prompt."""
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    await _seed_episodes(mm, 5)

    # Store an existing active strategy
    item = await mm.store_dream_insight(
        MemoryType.STRATEGY, "Existing strategy", 0.9, "default"
    )
    await mm.review_insight(item.id, accepted=True)

    # Store a rejected preference
    rejected = await mm.store_dream_insight(
        MemoryType.PREFERENCE, "Rejected preference", 0.7, "default"
    )
    await mm.review_insight(rejected.id, accepted=False)

    # Track what the LLM receives
    captured_messages: list[str] = []
    original_generate_json = fake_provider.generate_json

    async def capturing_generate_json(messages, **kwargs):
        for m in messages:
            captured_messages.append(m.content)
        return {"strategies": [], "preferences": []}

    fake_provider.generate_json = capturing_generate_json  # type: ignore

    dreamer = Dreamer(fake_provider, mm, retrieval)
    await dreamer.dream()

    assert len(captured_messages) == 1
    prompt = captured_messages[0]

    # Existing active strategy should be in the prompt
    assert "Existing strategy" in prompt
    # Rejected item should be in the rejected section
    assert "Rejected preference" in prompt


@pytest.mark.asyncio
async def test_dream_handles_llm_error_gracefully(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    await _seed_episodes(mm, 5)

    # Provider that raises
    provider = FakeLLMProvider()

    async def failing_generate_json(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    provider.generate_json = failing_generate_json  # type: ignore

    dreamer = Dreamer(provider, mm, retrieval)
    result = await dreamer.dream()

    assert result["strategies"] == 0
    assert result["preferences"] == 0
    assert "error" in result
    assert "LLM unavailable" in result["error"]


# ── Pending review lifecycle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_review_accept(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    item = await mm.store_dream_insight(
        MemoryType.STRATEGY, "User prefers list before read", 0.85, "default"
    )
    assert item.status == MemoryStatus.PENDING_REVIEW

    reviewed = await mm.review_insight(item.id, accepted=True)
    assert reviewed is not None
    assert reviewed.status == MemoryStatus.ACTIVE
    assert reviewed.content == "User prefers list before read"


@pytest.mark.asyncio
async def test_review_accept_with_edit(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    item = await mm.store_dream_insight(
        MemoryType.PREFERENCE, "User uses Python 3.11", 0.7, "default"
    )

    reviewed = await mm.review_insight(item.id, accepted=True, edited_content="User uses Python 3.13")
    assert reviewed is not None
    assert reviewed.status == MemoryStatus.ACTIVE
    assert reviewed.content == "User uses Python 3.13"


@pytest.mark.asyncio
async def test_review_reject(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    item = await mm.store_dream_insight(
        MemoryType.STRATEGY, "Incorrect pattern", 0.65, "default"
    )

    reviewed = await mm.review_insight(item.id, accepted=False)
    assert reviewed is not None
    assert reviewed.status == MemoryStatus.REJECTED


@pytest.mark.asyncio
async def test_review_nonexistent_returns_none(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    result = await mm.review_insight("nonexistent_id", accepted=True)
    assert result is None


@pytest.mark.asyncio
async def test_review_already_active_returns_none(db_path: Path) -> None:
    """Reviewing an already-active item should return None (not pending)."""
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    item = await mm.store_dream_insight(
        MemoryType.STRATEGY, "Some pattern", 0.8, "default"
    )
    await mm.review_insight(item.id, accepted=True)

    # Try reviewing again — it's no longer pending_review
    result = await mm.review_insight(item.id, accepted=True)
    assert result is None


@pytest.mark.asyncio
async def test_get_rejected_contents(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    item1 = await mm.store_dream_insight(MemoryType.STRATEGY, "Bad pattern", 0.7)
    item2 = await mm.store_dream_insight(MemoryType.PREFERENCE, "Wrong pref", 0.65)
    await mm.review_insight(item1.id, accepted=False)
    await mm.review_insight(item2.id, accepted=False)

    rejected = await mm.get_rejected_contents()
    assert "Bad pattern" in rejected
    assert "Wrong pref" in rejected


# ── FIFO eviction ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evict_lowest_confidence(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    # Create 3 active strategies with different confidences
    items = []
    for content, conf in [("Low", 0.6), ("Mid", 0.75), ("High", 0.9)]:
        item = await mm.store_dream_insight(MemoryType.STRATEGY, content, conf)
        await mm.review_insight(item.id, accepted=True)
        items.append(item)

    count = await mm.count_active_by_type("default", "strategy")
    assert count == 3

    evicted_id = await mm.evict_lowest_confidence("default", "strategy")
    assert evicted_id is not None

    # The lowest confidence item ("Low", 0.6) should be evicted
    remaining = await mm.list_items(memory_type="strategy")
    remaining_active = [r for r in remaining if r.status == MemoryStatus.ACTIVE]
    assert len(remaining_active) == 2
    remaining_contents = {r.content for r in remaining_active}
    assert "Low" not in remaining_contents
    assert "Mid" in remaining_contents
    assert "High" in remaining_contents


@pytest.mark.asyncio
async def test_count_active_by_type(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    # One active, one pending
    item1 = await mm.store_dream_insight(MemoryType.STRATEGY, "Active one", 0.8)
    await mm.review_insight(item1.id, accepted=True)
    await mm.store_dream_insight(MemoryType.STRATEGY, "Pending one", 0.7)

    count = await mm.count_active_by_type("default", "strategy")
    assert count == 1  # Only the accepted one


# ── _maybe_dream interval logic ─────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_dream_respects_interval(db_path: Path, fake_provider: FakeLLMProvider) -> None:
    """Simulate the orchestrator's _maybe_dream logic."""
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    fake_provider.set_response({"strategies": [], "preferences": []})
    dreamer = Dreamer(fake_provider, mm, retrieval)

    dream_interval = 5
    dream_called = False

    async def tracking_dream(workspace_id="default"):
        nonlocal dream_called
        dream_called = True
        return {"strategies": 0, "preferences": 0}

    dreamer.dream = tracking_dream  # type: ignore

    # Seed 4 episodes — should NOT trigger (below interval)
    await _seed_episodes(mm, 4)
    ep_count = await mm.episode_count()
    if ep_count >= dream_interval and ep_count % dream_interval == 0:
        await dreamer.dream()
    assert not dream_called

    # Add one more → 5 episodes → should trigger
    await mm.store_episode(content="Episode 5", source="test")
    ep_count = await mm.episode_count()
    assert ep_count == 5
    if ep_count >= dream_interval and ep_count % dream_interval == 0:
        await dreamer.dream()
    assert dream_called

    # 6 episodes → should NOT trigger (not on interval boundary)
    dream_called = False
    await mm.store_episode(content="Episode 6", source="test")
    ep_count = await mm.episode_count()
    assert ep_count == 6
    if ep_count >= dream_interval and ep_count % dream_interval == 0:
        await dreamer.dream()
    assert not dream_called


@pytest.mark.asyncio
async def test_maybe_dream_disabled_when_interval_zero(db_path: Path) -> None:
    """When dream_interval=0, dreaming should never trigger."""
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    dream_interval = 0
    await _seed_episodes(mm, 10)
    ep_count = await mm.episode_count()

    # Simulate the check
    should_dream = dream_interval > 0 and ep_count >= dream_interval and ep_count % dream_interval == 0
    assert not should_dream


# ── Planner context integration ──────────────────────────────────


@pytest.mark.asyncio
async def test_active_strategies_appear_in_planner_context(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    # Create and accept a strategy
    item = await mm.store_dream_insight(
        MemoryType.STRATEGY, "User always lists files before reading", 0.85
    )
    await mm.review_insight(item.id, accepted=True)

    context = await retrieval.get_context_for_planner("list some files")
    assert "Known Strategies" in context
    assert "User always lists files before reading" in context


@pytest.mark.asyncio
async def test_pending_strategies_excluded_from_planner_context(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    # Create a pending strategy (not yet accepted)
    await mm.store_dream_insight(
        MemoryType.STRATEGY, "Pending pattern should not appear", 0.85
    )

    context = await retrieval.get_context_for_planner("anything")
    assert "Pending pattern should not appear" not in context


@pytest.mark.asyncio
async def test_rejected_strategies_excluded_from_planner_context(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    item = await mm.store_dream_insight(
        MemoryType.STRATEGY, "Rejected pattern should not appear", 0.85
    )
    await mm.review_insight(item.id, accepted=False)

    context = await retrieval.get_context_for_planner("anything")
    assert "Rejected pattern should not appear" not in context


@pytest.mark.asyncio
async def test_active_preferences_appear_in_planner_context(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)
    retrieval = MemoryRetrieval(db_path)

    item = await mm.store_dream_insight(
        MemoryType.PREFERENCE, "User's project uses pytest", 0.78
    )
    await mm.review_insight(item.id, accepted=True)

    context = await retrieval.get_context_for_planner("run tests")
    assert "Inferred Preferences" in context
    assert "User's project uses pytest" in context


# ── store_dream_insight validation ───────────────────────────────


@pytest.mark.asyncio
async def test_store_dream_insight_rejects_invalid_type(db_path: Path) -> None:
    await create_tables(db_path)
    mm = MemoryManager(db_path)

    with pytest.raises(ValueError, match="strategy or preference"):
        await mm.store_dream_insight(MemoryType.FACT, "Not allowed", 0.8)

    with pytest.raises(ValueError, match="strategy or preference"):
        await mm.store_dream_insight(MemoryType.EPISODE, "Not allowed", 0.8)


# ── Database migration ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_recreates_old_memory_items_table(tmp_path: Path) -> None:
    """Simulate an old DB with the original CHECK constraint and verify migration."""
    from apps.api.database import get_connection, create_tables as full_create_tables

    db_path = tmp_path / "old.db"

    # 1. Create the OLD schema manually (original CHECK constraint, no status column)
    conn = await get_connection(db_path)
    try:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, created_at TEXT NOT NULL, run_id TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL DEFAULT 'default',
                status TEXT NOT NULL DEFAULT 'idle', user_message TEXT NOT NULL,
                plan TEXT, final_response TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_steps (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_index INTEGER NOT NULL,
                tool TEXT NOT NULL, args TEXT NOT NULL DEFAULT '{}', risk_level TEXT NOT NULL DEFAULT 'safe',
                status TEXT NOT NULL DEFAULT 'pending', result TEXT, error TEXT, started_at TEXT, finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
                payload TEXT NOT NULL, approved INTEGER, decided_at TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL, run_id TEXT, step_id TEXT,
                data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL DEFAULT 'default',
                memory_type TEXT NOT NULL CHECK (memory_type IN ('fact', 'episode', 'summary')),
                content TEXT NOT NULL, summary TEXT, source TEXT, confidence REAL DEFAULT 0.5,
                visibility TEXT NOT NULL DEFAULT 'user_visible',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, run_id TEXT
            );
            CREATE TABLE IF NOT EXISTS tool_manifests (
                name TEXT PRIMARY KEY, description TEXT NOT NULL, risk_level TEXT NOT NULL,
                approval_required INTEGER NOT NULL DEFAULT 0, input_schema TEXT NOT NULL DEFAULT '{}',
                output_schema TEXT NOT NULL DEFAULT '{}', registered_at TEXT NOT NULL
            );
        """)
        await conn.commit()

        # Insert a fact using the old schema
        await conn.execute(
            "INSERT INTO memory_items (id, workspace_id, memory_type, content, "
            "created_at, updated_at) VALUES ('old_fact', 'default', 'fact', "
            "'I existed before migration', '2025-01-01', '2025-01-01')"
        )
        await conn.commit()
    finally:
        await conn.close()

    # 2. Run the full create_tables (which includes migration)
    await full_create_tables(db_path)

    # 3. Verify we can now insert strategy/preference types
    mm = MemoryManager(db_path)
    item = await mm.store_dream_insight(MemoryType.STRATEGY, "New strategy", 0.8)
    assert item.memory_type == MemoryType.STRATEGY
    assert item.status == MemoryStatus.PENDING_REVIEW

    # 4. Verify old data survived the migration
    items = await mm.list_items(memory_type="fact")
    assert len(items) == 1
    assert items[0].content == "I existed before migration"
    assert items[0].status == MemoryStatus.ACTIVE  # default from migration
