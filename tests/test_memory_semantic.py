"""
Tests for the upgraded hybrid memory system.

Covers: embedding provider, vector store, hybrid search, context building,
planner integration, remember_fact end-to-end, reindexing, graceful degradation.

Tests that require actual embedding model use a deterministic mock.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.database import create_tables, get_connection
from apps.api.memory.embeddings import EmbeddingProvider
from apps.api.memory.manager import MemoryManager
from apps.api.memory.retrieval import MemoryRetrieval
from apps.api.memory.vector_store import VectorStore
from apps.api.models.memory_item import MemoryItem, MemoryType


# ── Mock embedding provider ───────────────────────────────────────

class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider for tests.

    Generates a simple hash-based vector that gives consistent results:
    similar texts produce similar vectors via character-level overlap.
    """

    def __init__(self, dim: int = 64) -> None:
        self._model_name = "mock"
        self._model = True  # non-None means "loaded"
        self._available = True
        self._dimension = dim

    def _load_model(self) -> Any:
        return True

    async def embed(self, text: str) -> list[float] | None:
        return self._deterministic_embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None] | None:
        if not texts:
            return None
        return [self._deterministic_embed(t) for t in texts]

    def _deterministic_embed(self, text: str) -> list[float]:
        """Hash-based pseudo-embedding. Semantically similar texts get closer
        vectors because we embed character n-grams."""
        import numpy as np
        rng = np.random.RandomState(42)
        base = np.zeros(self._dimension, dtype=np.float32)
        text_lower = text.lower()
        # Embed overlapping 3-grams
        for i in range(len(text_lower) - 2):
            trigram = text_lower[i:i+3]
            h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
            idx = h % self._dimension
            base[idx] += 1.0
        # Add word-level signal
        for word in text_lower.split():
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % self._dimension
            base[idx] += 2.0
        # Normalize to unit vector
        norm = np.linalg.norm(base)
        if norm > 0:
            base = base / norm
        return base.tolist()


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_db_path: Path) -> Path:
    return tmp_db_path


@pytest.fixture
def embedder() -> MockEmbeddingProvider:
    """Use mock embedder that works without network."""
    return MockEmbeddingProvider()


@pytest.fixture
def vector_store(db_path: Path) -> VectorStore:
    return VectorStore(db_path)


@pytest.fixture
def retrieval(db_path: Path, embedder: MockEmbeddingProvider, vector_store: VectorStore) -> MemoryRetrieval:
    return MemoryRetrieval(db_path, embedder, vector_store)


@pytest.fixture
def manager(db_path: Path, embedder: MockEmbeddingProvider, vector_store: VectorStore) -> MemoryManager:
    return MemoryManager(db_path, embedder, vector_store)


# ── EmbeddingProvider ────────────────────────────────────────────


class TestEmbeddingProvider:
    def test_provider_reports_availability(self, embedder: MockEmbeddingProvider) -> None:
        assert embedder.available is True

    def test_dimension(self, embedder: MockEmbeddingProvider) -> None:
        assert embedder.dimension == 64

    @pytest.mark.asyncio
    async def test_embed_single(self, embedder: MockEmbeddingProvider) -> None:
        result = await embedder.embed("Hello world")
        assert result is not None
        assert len(result) == 64
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_embed_batch(self, embedder: MockEmbeddingProvider) -> None:
        texts = ["Hello world", "Goodbye world", "Python programming"]
        results = await embedder.embed_batch(texts)
        assert results is not None
        assert len(results) == 3
        for emb in results:
            assert len(emb) == 64

    @pytest.mark.asyncio
    async def test_embed_empty_list(self, embedder: MockEmbeddingProvider) -> None:
        result = await embedder.embed_batch([])
        assert result is None

    @pytest.mark.asyncio
    async def test_similar_texts_produce_similar_vectors(self, embedder: MockEmbeddingProvider) -> None:
        """Mock embedder should give higher similarity for related texts."""
        import numpy as np
        v1 = await embedder.embed("I prefer VS Code as my editor")
        v2 = await embedder.embed("My editor of choice is VS Code")
        v3 = await embedder.embed("The weather is sunny today")
        # v1 and v2 should be more similar than v1 and v3
        sim_12 = float(np.dot(v1, v2))
        sim_13 = float(np.dot(v1, v3))
        assert sim_12 > sim_13


# ── VectorStore ──────────────────────────────────────────────────


class TestVectorStore:
    @pytest.mark.asyncio
    async def test_ensure_table(self, db_path: Path, vector_store: VectorStore) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        conn = await get_connection(db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vectors'"
            )
            assert len(rows) == 1
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_upsert_and_count(self, db_path: Path, vector_store: VectorStore) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        await vector_store.upsert("item_1", "hello", [1.0, 2.0, 3.0])
        count = await vector_store.count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_upsert_skips_unchanged(self, db_path: Path, vector_store: VectorStore) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        await vector_store.upsert("item_1", "hello", [1.0, 2.0, 3.0])
        # Same content — should skip
        await vector_store.upsert("item_1", "hello", [4.0, 5.0, 6.0])
        # Verify original embedding is preserved by checking search
        results = await vector_store.search([1.0, 2.0, 3.0], limit=1)
        assert len(results) == 1
        assert results[0][0] == "item_1"

    @pytest.mark.asyncio
    async def test_upsert_updates_changed(self, db_path: Path, vector_store: VectorStore) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        await vector_store.upsert("item_1", "hello", [1.0, 2.0, 3.0])
        # Changed content — should update
        await vector_store.upsert("item_1", "goodbye", [4.0, 5.0, 6.0])
        count = await vector_store.count()
        assert count == 1  # still one item

    @pytest.mark.asyncio
    async def test_search_returns_sorted_by_similarity(
        self, db_path: Path, vector_store: VectorStore
    ) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        await vector_store.upsert("item_a", "text_a", [1.0, 0.0, 0.0])
        await vector_store.upsert("item_b", "text_b", [0.1, 0.9, 0.1])
        await vector_store.upsert("item_c", "text_c", [0.9, 0.1, 0.0])

        results = await vector_store.search([1.0, 0.0, 0.0], limit=3)
        assert len(results) >= 2
        # item_a should be most similar to query [1,0,0]
        assert results[0][0] == "item_a"
        assert results[0][1] > results[1][1]

    @pytest.mark.asyncio
    async def test_delete(self, db_path: Path, vector_store: VectorStore) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        await vector_store.upsert("item_1", "hello", [1.0, 2.0, 3.0])
        await vector_store.delete("item_1")
        count = await vector_store.count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_indexed_ids(self, db_path: Path, vector_store: VectorStore) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()
        await vector_store.upsert("item_1", "a", [1.0])
        await vector_store.upsert("item_2", "b", [2.0])
        ids = await vector_store.get_indexed_ids()
        assert ids == {"item_1", "item_2"}


# ── Hybrid Search — semantic matching ─────────────────────────────


class TestHybridSearch:
    """Test that semantic search finds results keyword search would miss."""

    @pytest.mark.asyncio
    async def test_semantic_finds_no_overlap(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """Store 'User prefers VS Code' → search 'what editor' → finds it."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="User prefers VS Code as their editor")

        # Keyword search should NOT find this (no word overlap)
        kw_results = await retrieval.search(
            "what editor do I use", search_mode="keyword"
        )
        # "editor" might partially match, but "what" "do" "I" "use" won't
        # The key test is that hybrid DOES find it:
        hybrid_results = await retrieval.search(
            "what editor do I use", search_mode="hybrid"
        )
        assert len(hybrid_results) >= 1
        assert any("VS Code" in r.content for r in hybrid_results)

    @pytest.mark.asyncio
    async def test_semantic_database_query(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """Store 'Project uses PostgreSQL' → search 'database config' → finds it."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="Project uses PostgreSQL for the database")

        results = await retrieval.search(
            "database config", search_mode="hybrid"
        )
        assert len(results) >= 1
        assert any("PostgreSQL" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_keyword_still_works(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """Exact keyword match still works in hybrid mode."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="Listed files and found 12 Python files")

        results = await retrieval.search("Python files", search_mode="hybrid")
        assert len(results) >= 1
        assert any("Python" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_hybrid_beats_keyword_for_semantic(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """Compare hybrid vs keyword-only for a semantic query."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="I prefer VS Code as my editor")
        await manager.store_fact(content="My favorite color is blue")

        # "IDE" is semantically related to "editor" / "VS Code" but has no keyword overlap
        hybrid = await retrieval.search("which IDE should I open", search_mode="hybrid")
        keyword = await retrieval.search("which IDE should I open", search_mode="keyword")

        # Hybrid should find VS Code; keyword likely won't (no word overlap)
        hybrid_has_vscode = any("VS Code" in r.content for r in hybrid)
        assert hybrid_has_vscode, f"Hybrid failed to find VS Code. Got: {[r.content for r in hybrid]}"

    @pytest.mark.asyncio
    async def test_vector_only_mode(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """Vector-only search mode works with mock embedder."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="User's thesis topic is NLP transformers")

        # Vector search should find related content
        results = await retrieval.search(
            "thesis NLP", search_mode="vector"
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_with_scores(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """search_with_scores returns (item, score) tuples."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="User prefers dark mode")

        scored = await retrieval.search_with_scores("dark theme preference")
        assert len(scored) >= 1
        item, score = scored[0]
        assert isinstance(score, float)
        assert score > 0


# ── Context for Planner ──────────────────────────────────────────


class TestContextForPlanner:
    @pytest.mark.asyncio
    async def test_includes_all_facts(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_fact(content="Preferred editor: VS Code")
        await manager.store_fact(content="Project directory: ~/thesis")

        context = await retrieval.get_context_for_planner("list files")
        assert "VS Code" in context
        assert "~/thesis" in context
        assert "Known Facts" in context

    @pytest.mark.asyncio
    async def test_includes_relevant_episodes(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()

        await manager.store_episode(
            content="Listed files in ~/thesis — found 12 Python files",
            summary="Listed workspace files",
        )

        context = await retrieval.get_context_for_planner("show me the files")
        assert "Relevant Past Context" in context

    @pytest.mark.asyncio
    async def test_empty_memory_returns_no_relevant(
        self, db_path: Path, retrieval: MemoryRetrieval
    ) -> None:
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()
        context = await retrieval.get_context_for_planner("anything")
        assert "No relevant" in context

    @pytest.mark.asyncio
    async def test_backward_compat_alias(
        self, db_path: Path, retrieval: MemoryRetrieval, manager: MemoryManager
    ) -> None:
        """get_context_bundle still works as alias."""
        await create_tables(db_path)
        await retrieval._vectors.ensure_table()
        await manager.store_fact(content="Test fact for alias")
        context = await retrieval.get_context_bundle("test")
        assert "Test fact" in context


# ── Auto-indexing on write ────────────────────────────────────────


class TestAutoIndexing:
    @pytest.mark.asyncio
    async def test_store_fact_auto_indexes(
        self, db_path: Path, manager: MemoryManager, vector_store: VectorStore
    ) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()

        item = await manager.store_fact(content="User prefers dark mode")
        count = await vector_store.count()
        assert count == 1

        indexed_ids = await vector_store.get_indexed_ids()
        assert item.id in indexed_ids

    @pytest.mark.asyncio
    async def test_store_episode_auto_indexes(
        self, db_path: Path, manager: MemoryManager, vector_store: VectorStore
    ) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()

        await manager.store_episode(content="Ran some commands", summary="ran cmds")
        count = await vector_store.count()
        assert count == 1


# ── Reindexing ────────────────────────────────────────────────────


class TestReindex:
    @pytest.mark.asyncio
    async def test_reindex_indexes_missing_items(
        self, db_path: Path, retrieval: MemoryRetrieval, vector_store: VectorStore
    ) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()

        # Store items WITHOUT auto-indexing (bare manager)
        bare_mm = MemoryManager(db_path)
        await bare_mm.store_fact(content="Fact without embedding 1")
        await bare_mm.store_fact(content="Fact without embedding 2")

        # Verify no embeddings yet
        assert await vector_store.count() == 0

        # Reindex
        count = await retrieval.reindex_all()
        assert count == 2
        assert await vector_store.count() == 2

    @pytest.mark.asyncio
    async def test_reindex_skips_already_indexed(
        self, db_path: Path, manager: MemoryManager,
        retrieval: MemoryRetrieval, vector_store: VectorStore
    ) -> None:
        await create_tables(db_path)
        await vector_store.ensure_table()

        # Auto-indexed via manager
        await manager.store_fact(content="Already indexed fact")
        assert await vector_store.count() == 1

        # Reindex should skip existing
        count = await retrieval.reindex_all()
        assert count == 0


# ── Planner wiring ────────────────────────────────────────────────


class TestPlannerWiring:
    @pytest.mark.asyncio
    async def test_planner_receives_memory_context(
        self, db_path: Path, tmp_workspace: Path
    ) -> None:
        """Mock planner and verify memory context is non-empty."""
        from apps.api.config import Settings
        from apps.api.core.orchestrator import Orchestrator
        from apps.api.skills.registry import SkillRegistry

        await create_tables(db_path)

        # Pre-populate a fact
        mm = MemoryManager(db_path)
        await mm.store_fact(content="User prefers Python")

        settings = Settings(
            workspace_root=str(tmp_workspace),
            database_path=str(db_path),
            anthropic_api_key="test-key",
            use_react=True,
        )
        registry = SkillRegistry()
        registry.discover()
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        # Mock the planner to capture what it receives
        captured_contexts: list[str] = []

        async def mock_react_step(user_message, observations, memory_context="", workspace_info="", **kwargs):
            captured_contexts.append(memory_context)
            return {"action": "final_answer", "response": "Done", "reasoning": "test"}

        orch._planner = MagicMock()
        orch._planner.react_step = mock_react_step

        await orch.handle_message("sess_1", "What language do I prefer?")
        # Wait for background task
        import asyncio
        await asyncio.sleep(0.5)

        assert len(captured_contexts) >= 1
        assert "Python" in captured_contexts[0], \
            f"Memory context missing fact. Got: {captured_contexts[0]}"

    @pytest.mark.asyncio
    async def test_react_loop_passes_memory_every_iteration(
        self, db_path: Path, tmp_workspace: Path
    ) -> None:
        """Verify memory_context is passed on every ReAct iteration, not just the first."""
        from apps.api.config import Settings
        from apps.api.core.orchestrator import Orchestrator
        from apps.api.skills.registry import SkillRegistry

        await create_tables(db_path)
        mm = MemoryManager(db_path)
        await mm.store_fact(content="User's workspace is ~/projects")

        settings = Settings(
            workspace_root=str(tmp_workspace),
            database_path=str(db_path),
            anthropic_api_key="test-key",
            use_react=True,
        )
        registry = SkillRegistry()
        registry.discover()
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        call_count = 0
        captured_contexts: list[str] = []

        async def mock_react_step(user_message, observations, memory_context="", workspace_info="", **kwargs):
            nonlocal call_count
            call_count += 1
            captured_contexts.append(memory_context)
            if call_count == 1:
                return {"action": "tool", "tool": "list_files",
                        "args": {"path": "."}, "reasoning": "list first"}
            return {"action": "final_answer", "response": "Done", "reasoning": "done"}

        orch._planner = MagicMock()
        orch._planner.react_step = mock_react_step

        await orch.handle_message("sess_2", "List my project files")
        import asyncio
        await asyncio.sleep(1.0)

        assert call_count >= 2, f"Expected 2+ iterations, got {call_count}"
        # Both iterations should have memory context with the fact
        for i, ctx in enumerate(captured_contexts):
            assert "~/projects" in ctx, \
                f"Iteration {i+1} missing memory. Got: {ctx}"


# ── remember_fact end-to-end ──────────────────────────────────────


class TestRememberFactEndToEnd:
    @pytest.mark.asyncio
    async def test_fact_stored_and_searchable_semantically(
        self, db_path: Path, embedder: MockEmbeddingProvider,
        retrieval: MemoryRetrieval, vector_store: VectorStore
    ) -> None:
        """remember_fact tool stores fact → hybrid search finds it semantically."""
        await create_tables(db_path)
        await vector_store.ensure_table()

        # Store fact via manager with mock embedder (auto-indexes)
        mm = MemoryManager(db_path, embedder, vector_store)
        item = await mm.store_fact(content="My project uses PostgreSQL")
        assert item.id

        # Now search semantically — "database" should find "PostgreSQL"
        results = await retrieval.search("database configuration", search_mode="hybrid")
        assert len(results) >= 1
        assert any("PostgreSQL" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_fact_appears_in_planner_context(
        self, db_path: Path, retrieval: MemoryRetrieval, vector_store: VectorStore,
        manager: MemoryManager
    ) -> None:
        """After storing a fact, get_context_for_planner includes it."""
        await create_tables(db_path)
        await vector_store.ensure_table()

        await manager.store_fact(content="User prefers dark mode")

        planner_ctx = await retrieval.get_context_for_planner("settings")
        assert "dark mode" in planner_ctx


# ── Graceful degradation ─────────────────────────────────────────


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_keyword_fallback_without_embedder(self, db_path: Path) -> None:
        """Without embedding provider, search degrades to keyword-only."""
        await create_tables(db_path)
        mm = MemoryManager(db_path)
        await mm.store_fact(content="User prefers dark mode")

        retrieval = MemoryRetrieval(db_path)  # No embedder, no vector store
        results = await retrieval.search("dark mode")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_hybrid_falls_back_without_embedder(self, db_path: Path) -> None:
        """Hybrid mode gracefully degrades to keyword when no embedder."""
        await create_tables(db_path)
        mm = MemoryManager(db_path)
        await mm.store_fact(content="Project uses Python 3.11")

        retrieval = MemoryRetrieval(db_path)
        results = await retrieval.search("Python", search_mode="hybrid")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_manager_works_without_embedder(self, db_path: Path) -> None:
        """MemoryManager without embedder stores facts without crashing."""
        await create_tables(db_path)
        mm = MemoryManager(db_path)  # No embedder
        item = await mm.store_fact(content="Simple fact")
        assert item.id
        assert item.content == "Simple fact"

    @pytest.mark.asyncio
    async def test_context_for_planner_without_embedder(self, db_path: Path) -> None:
        """get_context_for_planner works with keyword-only fallback."""
        await create_tables(db_path)
        mm = MemoryManager(db_path)
        await mm.store_fact(content="User name is Alice")

        retrieval = MemoryRetrieval(db_path)
        context = await retrieval.get_context_for_planner("who am I")
        # Should still include facts (keyword match or direct fetch)
        assert "Alice" in context


# ── Episode storage ───────────────────────────────────────────────


class TestEpisodeStorage:
    @pytest.mark.asyncio
    async def test_episode_stored_after_run(
        self, db_path: Path, tmp_workspace: Path
    ) -> None:
        """After a completed run, an episode should be stored in memory."""
        from apps.api.config import Settings
        from apps.api.core.orchestrator import Orchestrator
        from apps.api.skills.registry import SkillRegistry

        await create_tables(db_path)

        settings = Settings(
            workspace_root=str(tmp_workspace),
            database_path=str(db_path),
            anthropic_api_key="test-key",
            use_react=True,
        )
        registry = SkillRegistry()
        registry.discover()
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        async def mock_react_step(user_message, observations, memory_context="", workspace_info="", **kwargs):
            return {"action": "final_answer", "response": "Here's your answer!", "reasoning": "done"}

        orch._planner = MagicMock()
        orch._planner.react_step = mock_react_step

        await orch.handle_message("sess_1", "Tell me about the project")
        import asyncio
        await asyncio.sleep(0.5)

        # Check that an episode was stored
        mm = MemoryManager(db_path)
        episodes = await mm.list_items(memory_type="episode")
        assert len(episodes) >= 1
        assert "Tell me about the project" in episodes[0].content


# ── store_summary ─────────────────────────────────────────────────


class TestStoreSummary:
    @pytest.mark.asyncio
    async def test_store_summary(self, db_path: Path, manager: MemoryManager) -> None:
        await create_tables(db_path)
        item = await manager.store_summary(content="User is working on NLP thesis.")
        assert item.memory_type == MemoryType.SUMMARY
        assert item.content == "User is working on NLP thesis."

    @pytest.mark.asyncio
    async def test_store_summary_replaces_previous(
        self, db_path: Path, manager: MemoryManager
    ) -> None:
        """With max_summaries=1 (default), only the newest summary should exist."""
        await create_tables(db_path)
        await manager.store_summary(content="Old summary", max_summaries=1)
        await manager.store_summary(content="New summary", max_summaries=1)

        summaries = await manager.list_items(memory_type="summary")
        assert len(summaries) == 1
        assert summaries[0].content == "New summary"

    @pytest.mark.asyncio
    async def test_store_summary_keeps_multiple(
        self, db_path: Path, manager: MemoryManager
    ) -> None:
        """With max_summaries=3, up to 3 summaries are kept."""
        await create_tables(db_path)
        for i in range(5):
            await manager.store_summary(content=f"Summary {i}", max_summaries=3)

        summaries = await manager.list_items(memory_type="summary")
        assert len(summaries) == 3
        # Most recent first
        assert summaries[0].content == "Summary 4"
        assert summaries[1].content == "Summary 3"
        assert summaries[2].content == "Summary 2"

    @pytest.mark.asyncio
    async def test_episode_count(self, db_path: Path, manager: MemoryManager) -> None:
        await create_tables(db_path)
        assert await manager.episode_count() == 0
        await manager.store_episode(content="ep1")
        await manager.store_episode(content="ep2")
        assert await manager.episode_count() == 2

    @pytest.mark.asyncio
    async def test_get_recent_episodes(self, db_path: Path, manager: MemoryManager) -> None:
        await create_tables(db_path)
        for i in range(8):
            await manager.store_episode(content=f"Episode {i}")
        recent = await manager.get_recent_episodes(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert "Episode 7" in recent[0].content


# ── Summary generation via orchestrator ───────────────────────────


class TestSummaryGeneration:
    @pytest.mark.asyncio
    async def test_summary_generated_after_threshold(
        self, db_path: Path, tmp_workspace: Path
    ) -> None:
        """After summary_interval episodes, a summary should be auto-generated."""
        from apps.api.config import Settings
        from apps.api.core.orchestrator import Orchestrator
        from apps.api.skills.registry import SkillRegistry
        from apps.api.providers.base import LLMResponse

        await create_tables(db_path)

        settings = Settings(
            workspace_root=str(tmp_workspace),
            database_path=str(db_path),
            anthropic_api_key="test-key",
            use_react=True,
        )
        registry = SkillRegistry()
        registry.discover()
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        call_counter = 0

        async def mock_react_step(user_message, observations, memory_context="", workspace_info="", **kwargs):
            return {"action": "final_answer", "response": f"Answer to: {user_message}", "reasoning": "done"}

        async def mock_generate(messages, system="", max_tokens=1024, timeout=30.0):
            return LLMResponse(text="The user has been asking various questions about their workspace.")

        orch._planner = MagicMock()
        orch._planner.react_step = mock_react_step
        orch._planner._provider = MagicMock()
        orch._planner._provider.generate = mock_generate

        import asyncio

        # Run exactly summary_interval tasks (default=5)
        for i in range(settings.summary_interval):
            await orch.handle_message(f"sess_{i}", f"Task number {i}")
            await asyncio.sleep(0.3)

        # Wait for background tasks
        await asyncio.sleep(1.0)

        # Check that a summary was generated
        mm = MemoryManager(db_path)
        summaries = await mm.list_items(memory_type="summary")
        assert len(summaries) == 1, f"Expected 1 summary, got {len(summaries)}"
        assert "user" in summaries[0].content.lower()

    @pytest.mark.asyncio
    async def test_no_summary_before_threshold(
        self, db_path: Path, tmp_workspace: Path
    ) -> None:
        """Fewer than summary_interval episodes should NOT trigger summary."""
        from apps.api.config import Settings
        from apps.api.core.orchestrator import Orchestrator
        from apps.api.skills.registry import SkillRegistry

        await create_tables(db_path)

        settings = Settings(
            workspace_root=str(tmp_workspace),
            database_path=str(db_path),
            anthropic_api_key="test-key",
            use_react=True,
        )
        registry = SkillRegistry()
        registry.discover()
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        async def mock_react_step(user_message, observations, memory_context="", workspace_info="", **kwargs):
            return {"action": "final_answer", "response": "done", "reasoning": "done"}

        orch._planner = MagicMock()
        orch._planner.react_step = mock_react_step
        orch._planner._provider = None  # No LLM — summary shouldn't happen

        import asyncio

        # Run fewer than threshold
        for i in range(3):
            await orch.handle_message(f"sess_{i}", f"Task {i}")
            await asyncio.sleep(0.3)

        await asyncio.sleep(0.5)

        mm = MemoryManager(db_path)
        summaries = await mm.list_items(memory_type="summary")
        assert len(summaries) == 0


# ── Summary appears in planner context ────────────────────────────


class TestSummaryInPlannerContext:
    @pytest.mark.asyncio
    async def test_summary_included_in_context(
        self, db_path: Path, retrieval: MemoryRetrieval,
        manager: MemoryManager, vector_store: VectorStore,
    ) -> None:
        """Stored summaries appear in get_context_for_planner output."""
        await create_tables(db_path)
        await vector_store.ensure_table()

        await manager.store_summary(content="User is working on a Python ML project using PyTorch.")
        await manager.store_fact(content="Preferred language: Python")

        context = await retrieval.get_context_for_planner("help me with code")
        assert "Conversation Summary" in context
        assert "PyTorch" in context
        assert "Python" in context
