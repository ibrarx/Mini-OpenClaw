"""
Tests for the self-reflection critique loop.

Validates that the planner can critique a final answer, optionally improve
it, and that the orchestrator correctly wires reflection into the run
lifecycle — including the flag gate and max-retries logic.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from apps.api.config import Settings
from apps.api.core.orchestrator import Orchestrator
from apps.api.core.planner import Planner
from apps.api.database import create_tables
from apps.api.models.run import ReflectionResult, RunStatus
from apps.api.providers.base import LLMMessage, LLMProvider, LLMResponse, LLMToolSchema
from apps.api.providers.errors import LLMProviderError
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# FakeProvider — canned response queue
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    """In-memory provider that returns queued responses."""

    name = "fake"

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses: list[Any] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def queue(self, *items: Any) -> "FakeProvider":
        self._responses.extend(items)
        return self

    async def generate(
        self, messages: list[LLMMessage], *, system: str | None = None,
        tools: list[LLMToolSchema] | None = None, max_tokens: int = 2048,
        temperature: float | None = None, timeout: float = 60.0,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "system": system, "method": "generate"})
        if not self._responses:
            raise LLMProviderError("No more responses queued")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, str):
            return LLMResponse(text=resp)
        if isinstance(resp, dict):
            return LLMResponse(text=json.dumps(resp))
        return resp

    async def generate_json(
        self, messages: list[LLMMessage], *, system: str | None = None,
        tools: list[LLMToolSchema] | None = None, max_tokens: int = 2048,
        temperature: float | None = None, timeout: float = 60.0,
    ) -> dict[str, Any] | list[Any]:
        self.calls.append({"messages": messages, "system": system, "method": "generate_json"})
        if not self._responses:
            raise LLMProviderError("No more responses queued")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, dict):
            return resp
        if isinstance(resp, list):
            return resp
        if isinstance(resp, str):
            return json.loads(resp)
        raise LLMProviderError(f"Unexpected response type: {type(resp)}")

    @property
    def model(self) -> str:
        return "fake-model"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def planner(fake_provider: FakeProvider, registry: SkillRegistry) -> Planner:
    return Planner(provider=fake_provider, registry=registry)


# ---------------------------------------------------------------------------
# ReflectionResult model tests
# ---------------------------------------------------------------------------


class TestReflectionResultModel:
    """Test the ReflectionResult Pydantic model."""

    def test_defaults(self) -> None:
        r = ReflectionResult()
        assert r.overall_score == 1.0
        assert r.issues == []
        assert r.suggestion == ""
        assert r.improved is False
        assert r.attempt == 0

    def test_serialization_roundtrip(self) -> None:
        r = ReflectionResult(
            overall_score=0.65,
            completeness=0.5,
            accuracy=0.8,
            clarity=0.7,
            issues=["Missing details", "Inaccurate claim"],
            suggestion="Add more data",
            improved=True,
            attempt=1,
        )
        json_str = r.model_dump_json()
        restored = ReflectionResult.model_validate_json(json_str)
        assert restored.overall_score == 0.65
        assert restored.issues == ["Missing details", "Inaccurate claim"]
        assert restored.improved is True
        assert restored.attempt == 1

    def test_dict_roundtrip(self) -> None:
        r = ReflectionResult(overall_score=0.9, issues=["minor issue"])
        d = r.model_dump()
        assert d["overall_score"] == 0.9
        assert d["issues"] == ["minor issue"]
        restored = ReflectionResult.model_validate(d)
        assert restored == r


# ---------------------------------------------------------------------------
# Planner reflection method tests
# ---------------------------------------------------------------------------


class TestPlannerReflection:
    """Test the planner's reflect_on_answer method."""

    @pytest.mark.asyncio
    async def test_reflect_high_score(self, planner: Planner, fake_provider: FakeProvider) -> None:
        fake_provider.queue({
            "overall_score": 0.95,
            "completeness": 0.9,
            "accuracy": 1.0,
            "clarity": 0.95,
            "issues": [],
            "suggestion": "",
        })
        result = await planner.reflect_on_answer(
            user_message="List files",
            final_answer="Here are the files: a.txt, b.txt",
            observations_summary="- list_files: success",
        )
        assert result["overall_score"] == 0.95
        assert result["issues"] == []

    @pytest.mark.asyncio
    async def test_reflect_low_score(self, planner: Planner, fake_provider: FakeProvider) -> None:
        fake_provider.queue({
            "overall_score": 0.4,
            "completeness": 0.3,
            "accuracy": 0.5,
            "clarity": 0.4,
            "issues": ["Missing half the files", "Vague descriptions"],
            "suggestion": "Include all files with sizes",
        })
        result = await planner.reflect_on_answer(
            user_message="List all files with sizes",
            final_answer="Here are some files.",
            observations_summary="- list_files: success → {'entries': [...10 files...]}",
        )
        assert result["overall_score"] == 0.4
        assert len(result["issues"]) == 2

    @pytest.mark.asyncio
    async def test_reflect_provider_failure_is_non_fatal(self, planner: Planner, fake_provider: FakeProvider) -> None:
        fake_provider.queue(LLMProviderError("API timeout"))
        result = await planner.reflect_on_answer(
            user_message="Hello",
            final_answer="Hi there",
            observations_summary="",
        )
        # Should return a safe default, not raise
        assert result["overall_score"] == 1.0
        assert result["issues"] == []

    @pytest.mark.asyncio
    async def test_reflect_no_provider(self, registry: SkillRegistry) -> None:
        planner = Planner(provider=None, registry=registry)
        result = await planner.reflect_on_answer(
            user_message="Hello",
            final_answer="Hi",
            observations_summary="",
        )
        assert result["overall_score"] == 1.0

    @pytest.mark.asyncio
    async def test_reflect_sets_defaults(self, planner: Planner, fake_provider: FakeProvider) -> None:
        """Ensure missing fields in LLM response get safe defaults."""
        fake_provider.queue({"accuracy": 0.5})  # Missing overall_score, issues, suggestion
        result = await planner.reflect_on_answer(
            user_message="Test",
            final_answer="Test answer",
            observations_summary="",
        )
        assert "overall_score" in result
        assert "issues" in result
        assert "suggestion" in result


class TestPlannerImproveAnswer:
    """Test the planner's improve_answer method."""

    @pytest.mark.asyncio
    async def test_improve_returns_better_answer(self, planner: Planner, fake_provider: FakeProvider) -> None:
        fake_provider.queue("Here are all 10 files with their sizes: a.txt (1KB), b.txt (2KB)...")
        result = await planner.improve_answer(
            user_message="List all files with sizes",
            original_answer="Here are some files.",
            critique={"issues": ["Missing files"], "suggestion": "Include all files"},
            observations_summary="list_files returned 10 entries",
        )
        assert "10 files" in result

    @pytest.mark.asyncio
    async def test_improve_failure_returns_original(self, planner: Planner, fake_provider: FakeProvider) -> None:
        fake_provider.queue(LLMProviderError("API timeout"))
        result = await planner.improve_answer(
            user_message="Test",
            original_answer="Original answer",
            critique={"issues": ["problem"], "suggestion": "fix it"},
            observations_summary="",
        )
        assert result == "Original answer"

    @pytest.mark.asyncio
    async def test_improve_no_provider(self, registry: SkillRegistry) -> None:
        planner = Planner(provider=None, registry=registry)
        result = await planner.improve_answer(
            user_message="Test",
            original_answer="Original",
            critique={},
            observations_summary="",
        )
        assert result == "Original"


# ---------------------------------------------------------------------------
# Orchestrator integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    await create_tables(p)
    return p


class TestOrchestratorReflection:
    """Test that the orchestrator correctly runs (or skips) reflection."""

    def _make_orchestrator(
        self,
        settings: Settings,
        registry: SkillRegistry,
        provider: FakeProvider,
    ) -> Orchestrator:
        """Build an orchestrator with an injected provider."""
        orch = Orchestrator(settings, registry)
        planner = Planner(provider, registry)
        orch._planner = planner
        return orch

    @pytest.mark.asyncio
    async def test_reflection_skipped_when_disabled(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """When react_self_reflect=False, no reflection occurs."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=False,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # Queue: react_step returns final_answer immediately
        provider.queue({"action": "final_answer", "response": "Hello!", "reasoning": "Done"})

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Say hello")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.reflection is None
        # Only 1 call: the react_step. No reflection calls.
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_reflection_runs_when_enabled_high_score(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """When enabled and score >= threshold, reflection is stored but answer unchanged."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_max_retries=1,
            react_reflect_quality_threshold=0.7,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # react_step → final_answer
        provider.queue({"action": "final_answer", "response": "Great answer!", "reasoning": "Done"})
        # reflect_on_answer → high score
        provider.queue({
            "overall_score": 0.9,
            "completeness": 0.9,
            "accuracy": 0.9,
            "clarity": 0.9,
            "issues": [],
            "suggestion": "",
        })

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Do something")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Great answer!"
        assert run.reflection is not None
        assert run.reflection.overall_score == 0.9
        assert run.reflection.improved is False

    @pytest.mark.asyncio
    async def test_reflection_improves_answer_on_low_score(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """When score < threshold, improve_answer is called and answer is rewritten."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_max_retries=1,
            react_reflect_quality_threshold=0.7,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # react_step → final_answer
        provider.queue({"action": "final_answer", "response": "Bad answer", "reasoning": "Done"})
        # reflect_on_answer → low score (attempt 0)
        provider.queue({
            "overall_score": 0.4,
            "completeness": 0.3,
            "accuracy": 0.5,
            "clarity": 0.4,
            "issues": ["Incomplete"],
            "suggestion": "Add details",
        })
        # improve_answer → better text
        provider.queue("Much better answer with all the details")
        # reflect_on_answer → second attempt (attempt 1 = max_retries, last attempt)
        provider.queue({
            "overall_score": 0.85,
            "completeness": 0.9,
            "accuracy": 0.8,
            "clarity": 0.85,
            "issues": [],
            "suggestion": "",
        })

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Do something")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Much better answer with all the details"
        assert run.reflection is not None
        assert run.reflection.overall_score == 0.85
        assert run.reflection.attempt == 1

    @pytest.mark.asyncio
    async def test_reflection_failure_is_non_fatal(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """If reflection throws, the run still completes."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_max_retries=0,
            react_reflect_quality_threshold=0.7,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # react_step → final_answer
        provider.queue({"action": "final_answer", "response": "Good answer", "reasoning": "Done"})
        # reflect_on_answer → exception
        provider.queue(LLMProviderError("API exploded"))

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Test")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Good answer"
        # Reflection result exists but with default score (from the except branch)
        assert run.reflection is not None
        assert run.reflection.attempt == 0

    @pytest.mark.asyncio
    async def test_max_retries_respected(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """With max_retries=0, only one reflection attempt (no improvement)."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_max_retries=0,
            react_reflect_quality_threshold=0.7,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # react_step → final_answer
        provider.queue({"action": "final_answer", "response": "Mediocre answer", "reasoning": "Done"})
        # reflect_on_answer → low score, but max_retries=0 so no improvement
        provider.queue({
            "overall_score": 0.4,
            "completeness": 0.3,
            "accuracy": 0.5,
            "clarity": 0.4,
            "issues": ["Incomplete"],
            "suggestion": "Add more",
        })

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Test")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        # Answer is NOT changed because max_retries=0 (attempt 0 is the last)
        assert run.final_response == "Mediocre answer"
        assert run.reflection is not None
        assert run.reflection.overall_score == 0.4
        assert run.reflection.improved is False

    @pytest.mark.asyncio
    async def test_reflection_persisted_in_db(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """Verify reflection survives a save→load cycle."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_max_retries=0,
            react_reflect_quality_threshold=0.5,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        provider.queue({"action": "final_answer", "response": "Answer", "reasoning": "Done"})
        provider.queue({
            "overall_score": 0.8,
            "completeness": 0.7,
            "accuracy": 0.9,
            "clarity": 0.8,
            "issues": ["Minor"],
            "suggestion": "",
        })

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Test")
        await orch.wait_pending()

        # Load from DB
        loaded = await orch.get_run(run.run_id)
        assert loaded is not None
        assert loaded.reflection is not None
        assert loaded.reflection.overall_score == 0.8
        assert loaded.reflection.issues == ["Minor"]
