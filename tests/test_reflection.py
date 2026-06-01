"""
Tests for the self-reflection critique with loop re-entry.

Validates that:
- The planner can critique a final answer and return quality scores
- The orchestrator re-enters the ReAct loop when the score is low and budget remains
- The orchestrator falls back to text rewrite when no iteration budget is left
- Reflection is skipped when the flag is disabled or for child runs
- Critique failures are non-fatal
- Reflection results survive DB persistence
"""
from __future__ import annotations

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
    ) -> tuple[dict[str, Any] | list[Any], Any]:
        from apps.api.providers.base import TokenUsage
        self.calls.append({"messages": messages, "system": system, "method": "generate_json"})
        if not self._responses:
            raise LLMProviderError("No more responses queued")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, dict):
            return resp, TokenUsage()
        if isinstance(resp, list):
            return resp, TokenUsage()
        if isinstance(resp, str):
            return json.loads(resp), TokenUsage()
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
        assert r.reentry is False
        assert r.attempt == 0

    def test_serialization_roundtrip(self) -> None:
        r = ReflectionResult(
            overall_score=0.65,
            completeness=0.5,
            accuracy=0.8,
            clarity=0.7,
            issues=["Missing details", "Inaccurate claim"],
            suggestion="Add more data",
            reentry=True,
            attempt=1,
        )
        json_str = r.model_dump_json()
        restored = ReflectionResult.model_validate_json(json_str)
        assert restored.overall_score == 0.65
        assert restored.issues == ["Missing details", "Inaccurate claim"]
        assert restored.reentry is True
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
        fake_provider.queue({"accuracy": 0.5})
        result = await planner.reflect_on_answer(
            user_message="Test",
            final_answer="Test answer",
            observations_summary="",
        )
        assert "overall_score" in result
        assert "issues" in result
        assert "suggestion" in result


class TestPlannerImproveAnswer:
    """Test the planner's improve_answer method (text-only fallback)."""

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
        provider.queue({"action": "final_answer", "response": "Hello!", "reasoning": "Done"})

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Say hello")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.reflection is None
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_reflection_high_score_passes(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """When score >= threshold, reflection is stored and answer unchanged."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_quality_threshold=0.7,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        provider.queue({"action": "final_answer", "response": "Great answer!", "reasoning": "Done"})
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
        assert run.reflection.reentry is False

    @pytest.mark.asyncio
    async def test_reflection_low_score_reenters_loop(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """When score < threshold and budget remains, agent re-enters the loop."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_quality_threshold=0.7,
            react_max_iterations=5,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # Iteration 1: agent gives a bad final_answer
        provider.queue({"action": "final_answer", "response": "Bad answer", "reasoning": "Done"})
        # Reflection: low score
        provider.queue({
            "overall_score": 0.4,
            "completeness": 0.3,
            "accuracy": 0.5,
            "clarity": 0.4,
            "issues": ["Incomplete"],
            "suggestion": "Use list_files to get the data",
        })
        # Iteration 2: agent sees the critique and gives a better final_answer
        provider.queue({"action": "final_answer", "response": "Much better answer!", "reasoning": "Fixed it"})
        # Reflection on second attempt: passes this time
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
        assert run.final_response == "Much better answer!"
        assert run.iterations == 2  # used 2 iterations
        # The final reflection should be the passing one
        assert run.reflection is not None
        assert run.reflection.overall_score == 0.85
        # Should have a _reflection observation injected
        reflection_obs = [o for o in run.observations if o.tool == "_reflection"]
        assert len(reflection_obs) == 1

    @pytest.mark.asyncio
    async def test_reflection_low_score_text_rewrite_when_no_budget(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """When score < threshold but no iterations left, falls back to text rewrite."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_quality_threshold=0.7,
            react_max_iterations=1,  # only 1 iteration — no budget for re-entry
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # Iteration 1 (the only one): bad final_answer
        provider.queue({"action": "final_answer", "response": "Bad answer", "reasoning": "Done"})
        # Reflection: low score
        provider.queue({
            "overall_score": 0.4,
            "completeness": 0.3,
            "accuracy": 0.5,
            "clarity": 0.4,
            "issues": ["Incomplete"],
            "suggestion": "Add details",
        })
        # improve_answer (text-only fallback)
        provider.queue("Rewritten answer with more details")

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Do something")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Rewritten answer with more details"
        assert run.reflection is not None
        assert run.reflection.improved is True
        assert run.reflection.reentry is False
        assert run.iterations == 1

    @pytest.mark.asyncio
    async def test_reflection_failure_is_non_fatal(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """If the critique throws, the run still completes with the original answer."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_quality_threshold=0.7,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        provider.queue({"action": "final_answer", "response": "Good answer", "reasoning": "Done"})
        provider.queue(LLMProviderError("API exploded"))

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Test")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Good answer"
        # Planner's reflect_on_answer catches the error and returns a safe
        # default (score=1.0), so _run_critique returns a passing result.
        # The important thing is the run completed — no crash.
        assert run.reflection is not None
        assert run.reflection.overall_score == 1.0  # safe default
        assert run.reflection.reentry is False

    @pytest.mark.asyncio
    async def test_reflection_reentry_consumes_iteration_budget(
        self, tmp_workspace: Path, db_path: Path, registry: SkillRegistry,
    ) -> None:
        """Re-entry uses iteration budget. With max=2, first attempt + re-entry = 2."""
        settings = Settings(
            workspace_root=tmp_workspace,
            database_path=db_path,
            use_react=True,
            react_self_reflect=True,
            react_reflect_quality_threshold=0.7,
            react_max_iterations=2,
            anthropic_api_key="fake",
            react_use_goals=False,
        )
        provider = FakeProvider()
        # Iteration 1: bad answer
        provider.queue({"action": "final_answer", "response": "Bad", "reasoning": "Done"})
        # Reflection: fail
        provider.queue({"overall_score": 0.3, "issues": ["Bad"], "suggestion": "Fix it"})
        # Iteration 2 (re-entry): better answer
        provider.queue({"action": "final_answer", "response": "Better", "reasoning": "Fixed"})
        # Reflection: pass
        provider.queue({"overall_score": 0.9, "issues": [], "suggestion": ""})

        orch = self._make_orchestrator(settings, registry, provider)
        run = await orch.handle_message("sess1", "Test")
        await orch.wait_pending()

        run = await orch.get_run(run.run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.iterations == 2
        assert run.final_response == "Better"

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

        loaded = await orch.get_run(run.run_id)
        assert loaded is not None
        assert loaded.reflection is not None
        assert loaded.reflection.overall_score == 0.8
        assert loaded.reflection.issues == ["Minor"]
        assert loaded.reflection.reentry is False
