"""
Integration tests — end-to-end with a fake provider, real tools, real DB.

After the LLM-provider refactor, the planner depends on
``apps.api.providers.base.LLMProvider`` rather than a concrete SDK. These
tests inject an in-memory ``FakeProvider`` test double, so no network call
ever happens and no real API key is needed.

Validates: direct answer, safe tool execution, approval flow, rejection,
multi-step plans, missing-provider behaviour, memory round-trip.
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
from apps.api.memory.manager import MemoryManager
from apps.api.models.run import RunStatus
from apps.api.providers.base import LLMMessage, LLMProvider, LLMResponse, LLMToolSchema
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fake provider — same shape as the one used by test_planner.py
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    """In-memory provider. Returns canned text responses in FIFO order."""

    name = "fake"

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses: list[Any] = list(responses or [])
        self._model = "fake-1"
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[LLMToolSchema] | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "system": system})
        if not self._responses:
            # Defensive fallback so a test that under-queues responses fails
            # with a clear assertion rather than a cryptic IndexError.
            raise AssertionError(
                "FakeProvider: ran out of queued responses (test under-queued)"
            )
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=str(item))


def _install_fake_provider(orch: Orchestrator, responses: list[Any]) -> FakeProvider:
    """Swap the orchestrator's planner with one backed by a FakeProvider.

    This is the single point of integration between the test double and the
    refactored planner. After this call, every LLM round-trip the orchestrator
    drives will consume one entry from ``responses``.
    """
    fake = FakeProvider(responses)
    orch._planner = Planner(provider=fake, registry=orch._registry)
    return fake


def _plan_json(plan: dict[str, Any]) -> str:
    """Serialise a plan dict the way the LLM would return it."""
    return json.dumps(plan)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def populated_workspace(tmp_workspace: Path) -> Path:
    (tmp_workspace / "README.md").write_text("# Test\nHello world\n")
    (tmp_workspace / "notes.txt").write_text("Some notes\n")
    return tmp_workspace


def _make_settings(workspace: Path, db_path: Path) -> Settings:
    """Create a Settings instance for testing.

    We seed ``anthropic_api_key`` so that the orchestrator's factory call
    succeeds and creates a (real but unused) provider, which we then
    immediately replace with a FakeProvider via _install_fake_provider.
    """
    return Settings(
        llm_provider="anthropic",
        anthropic_api_key="test-fake",
        workspace_root=workspace,
        database_path=db_path,
        use_react=False,
    )


# ---------------------------------------------------------------------------
# Direct answer flow
# ---------------------------------------------------------------------------


class TestDirectAnswer:
    @pytest.mark.asyncio
    async def test_direct_answer_completes(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)
        _install_fake_provider(
            orch,
            [
                _plan_json(
                    {
                        "task_type": "direct_answer",
                        "confidence": 0.95,
                        "reasoning": "Simple question",
                        "direct_response": "A README is a documentation file.",
                        "steps": [],
                    }
                )
            ],
        )

        run = await orch.handle_message("sess_1", "What is a README?")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "A README is a documentation file."


# ---------------------------------------------------------------------------
# Safe tool execution
# ---------------------------------------------------------------------------


class TestSafeToolExecution:
    @pytest.mark.asyncio
    async def test_list_files_executes(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)
        _install_fake_provider(
            orch,
            [
                # First call: the plan.
                _plan_json(
                    {
                        "task_type": "tool_needed",
                        "confidence": 0.9,
                        "reasoning": "list files",
                        "steps": [
                            {
                                "step_id": "s1",
                                "tool": "list_files",
                                "args": {"path": "."},
                                "risk_level": "safe",
                            }
                        ],
                    }
                ),
                # Second call: the post-execution summary (plain text).
                "Found README.md and notes.txt",
            ],
        )

        run = await orch.handle_message("sess_1", "List files")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# Approval flow
# ---------------------------------------------------------------------------


class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_write_file_pauses_for_approval(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)
        _install_fake_provider(
            orch,
            [
                _plan_json(
                    {
                        "task_type": "tool_needed",
                        "confidence": 0.9,
                        "reasoning": "create file",
                        "steps": [
                            {
                                "step_id": "s1",
                                "tool": "write_file",
                                "args": {
                                    "path": "test.txt",
                                    "content": "hello",
                                    "mode": "create",
                                },
                                "risk_level": "medium",
                            }
                        ],
                    }
                )
            ],
        )

        run = await orch.handle_message("sess_1", "Create test.txt")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.AWAITING_APPROVAL

    @pytest.mark.asyncio
    async def test_approve_executes_and_completes(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)
        _install_fake_provider(
            orch,
            [
                _plan_json(
                    {
                        "task_type": "tool_needed",
                        "confidence": 0.9,
                        "reasoning": "create file",
                        "steps": [
                            {
                                "step_id": "s1",
                                "tool": "write_file",
                                "args": {
                                    "path": "test.txt",
                                    "content": "hello",
                                    "mode": "create",
                                },
                                "risk_level": "medium",
                            }
                        ],
                    }
                ),
                # Summary after execution
                "File created.",
            ],
        )

        run = await orch.handle_message("sess_1", "Create test.txt")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.AWAITING_APPROVAL

        await orch.approve_step(run.run_id, "s1", True)

        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED
        assert (tmp_workspace / "test.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_reject_cancels_run(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)
        _install_fake_provider(
            orch,
            [
                _plan_json(
                    {
                        "task_type": "tool_needed",
                        "confidence": 0.9,
                        "reasoning": "create file",
                        "steps": [
                            {
                                "step_id": "s1",
                                "tool": "write_file",
                                "args": {
                                    "path": "test.txt",
                                    "content": "hello",
                                    "mode": "create",
                                },
                                "risk_level": "medium",
                            }
                        ],
                    }
                )
            ],
        )

        run = await orch.handle_message("sess_1", "Create test.txt")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        await orch.approve_step(run.run_id, "s1", False)

        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.CANCELLED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.CANCELLED


# ---------------------------------------------------------------------------
# No provider configured
# ---------------------------------------------------------------------------


class TestNoApiKey:
    @pytest.mark.asyncio
    async def test_missing_api_key_fails_gracefully(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        await create_tables(tmp_db_path)
        # Both keys empty → factory raises ProviderConfigError → planner is None.
        settings = Settings(
            llm_provider="anthropic",
            anthropic_api_key="",
            gemini_api_key="",
            workspace_root=tmp_workspace,
            database_path=tmp_db_path,
        )
        orch = Orchestrator(settings, registry)

        run = await orch.handle_message("sess_1", "hello")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.FAILED
        # Message now references both provider keys; assert on a stable token.
        assert "provider" in run.final_response.lower() or "api key" in run.final_response.lower()


# ---------------------------------------------------------------------------
# Provider switching — make sure Gemini-selected settings also work
# ---------------------------------------------------------------------------


class TestProviderSwitching:
    @pytest.mark.asyncio
    async def test_gemini_provider_drives_orchestrator(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path
    ) -> None:
        """LLM_PROVIDER=gemini + GEMINI_API_KEY → orchestrator builds Gemini provider.

        We still inject FakeProvider for the actual LLM round-trip so the test
        doesn't hit the network. What we're validating here is that the
        factory chose Gemini and didn't blow up.
        """
        await create_tables(tmp_db_path)
        settings = Settings(
            llm_provider="gemini",
            anthropic_api_key="",
            gemini_api_key="test-fake-gemini",
            workspace_root=tmp_workspace,
            database_path=tmp_db_path,
            use_react=False,
        )
        orch = Orchestrator(settings, registry)
        # Confirm the factory built a Gemini provider before we swap it.
        assert orch._planner is not None
        assert orch._planner._provider.name == "gemini"

        _install_fake_provider(
            orch,
            [
                _plan_json(
                    {
                        "task_type": "direct_answer",
                        "confidence": 0.99,
                        "reasoning": "trivial",
                        "direct_response": "Hello from Gemini!",
                        "steps": [],
                    }
                )
            ],
        )

        run = await orch.handle_message("sess_1", "say hi")
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Hello from Gemini!"


# ---------------------------------------------------------------------------
# Memory round-trip
# ---------------------------------------------------------------------------


class TestMemoryRoundTrip:
    @pytest.mark.asyncio
    async def test_fact_stored_and_searchable(self, tmp_db_path: Path) -> None:
        await create_tables(tmp_db_path)
        mm = MemoryManager(tmp_db_path)
        item = await mm.store_fact(
            content="User prefers dark mode",
            source="test",
        )
        assert item.id

        from apps.api.memory.retrieval import MemoryRetrieval

        retrieval = MemoryRetrieval(tmp_db_path)
        results = await retrieval.search("dark mode")
        assert len(results) >= 1
        assert any("dark mode" in r.content for r in results)
