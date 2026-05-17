"""
Tests for the ReAct loop — iterative think → act → observe execution.

These tests exercise the full ReAct path through the orchestrator and
planner, using the same FakeProvider pattern as the existing test suite.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from apps.api.config import Settings
from apps.api.core.orchestrator import Orchestrator
from apps.api.core.planner import Planner, PlannerError
from apps.api.database import create_tables
from apps.api.models.run import RunStatus, Observation, RetryPolicy
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
        self.calls.append({"messages": messages, "system": system})
        if not self._responses:
            raise RuntimeError("FakeProvider has no queued response")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=str(item))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _react_json(obj: dict[str, Any]) -> str:
    """Serialize a ReAct decision the way the LLM would."""
    return json.dumps(obj)


def _make_settings(workspace: Path, db_path: Path) -> Settings:
    return Settings(
        llm_provider="anthropic",
        anthropic_api_key="test-fake",
        workspace_root=workspace,
        database_path=db_path,
        use_react=True,
        react_max_iterations=10,
        react_use_goals=False,
        react_max_replans=0,
    )


def _install_fake_provider(orch: Orchestrator, responses: list[Any]) -> FakeProvider:
    fake = FakeProvider(responses)
    orch._planner = Planner(provider=fake, registry=orch._registry)
    return fake


async def _wait_for_run(orch: Orchestrator, run_id: str, timeout: float = 10.0) -> Any:
    """Poll until the run reaches a terminal state, then await background cleanup."""
    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    for _ in range(int(timeout / 0.1)):
        run = await orch.get_run(run_id)
        if run and run.status in terminal:
            # Let background tasks (episode storage, etc.) finish
            await orch.wait_pending()
            return run
        await asyncio.sleep(0.1)
    # Timeout — drain what we can
    try:
        await asyncio.wait_for(orch.wait_pending(), timeout=2.0)
    except asyncio.TimeoutError:
        pass
    return await orch.get_run(run_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def populated_workspace(tmp_workspace: Path) -> Path:
    (tmp_workspace / "README.md").write_text("# Test\nHello world\n")
    (tmp_workspace / "src").mkdir()
    (tmp_workspace / "src" / "main.py").write_text("print('hello')\n")
    return tmp_workspace


# ---------------------------------------------------------------------------
# Planner.react_step() unit tests
# ---------------------------------------------------------------------------


class TestReactStep:
    """Unit tests for Planner.react_step()."""

    @pytest.mark.asyncio
    async def test_tool_action(self, registry: SkillRegistry) -> None:
        provider = FakeProvider()
        planner = Planner(provider=provider, registry=registry)
        provider.queue(_react_json({
            "action": "tool",
            "tool": "list_files",
            "args": {"path": "."},
            "reasoning": "Need to see workspace contents",
        }))
        result = await planner.react_step(
            user_message="List files",
            observations=[],
        )
        assert result["action"] == "tool"
        assert result["tool"] == "list_files"

    @pytest.mark.asyncio
    async def test_final_answer_action(self, registry: SkillRegistry) -> None:
        provider = FakeProvider()
        planner = Planner(provider=provider, registry=registry)
        provider.queue(_react_json({
            "action": "final_answer",
            "response": "The capital of France is Paris.",
            "reasoning": "Simple factual question",
        }))
        result = await planner.react_step(
            user_message="What is the capital of France?",
            observations=[],
        )
        assert result["action"] == "final_answer"
        assert result["response"] == "The capital of France is Paris."

    @pytest.mark.asyncio
    async def test_invalid_action_raises(self, registry: SkillRegistry) -> None:
        provider = FakeProvider()
        planner = Planner(provider=provider, registry=registry)
        provider.queue(_react_json({
            "action": "invalid_thing",
        }))
        with pytest.raises(PlannerError, match="Invalid action"):
            await planner.react_step("test", [])

    @pytest.mark.asyncio
    async def test_observations_passed_to_provider(self, registry: SkillRegistry) -> None:
        provider = FakeProvider()
        planner = Planner(provider=provider, registry=registry)
        provider.queue(_react_json({
            "action": "final_answer",
            "response": "Done",
            "reasoning": "All observations processed",
        }))
        observations = [
            {"tool": "list_files", "status": "success", "output": ["a.txt", "b.txt"]},
            {"tool": "read_file", "status": "error", "error": "not found"},
        ]
        await planner.react_step("test", observations)
        # Verify the observations appear in the user message sent to provider
        call = provider.calls[0]
        content = call["messages"][0].content
        assert "list_files" in content
        assert "read_file" in content

    @pytest.mark.asyncio
    async def test_no_provider_returns_final_answer(self, registry: SkillRegistry) -> None:
        planner = Planner(provider=None, registry=registry)
        result = await planner.react_step("test", [])
        assert result["action"] == "final_answer"
        assert "API key" in result["response"]

    @pytest.mark.asyncio
    async def test_provider_error_raises_planner_error(self, registry: SkillRegistry) -> None:
        provider = FakeProvider()
        planner = Planner(provider=provider, registry=registry)
        provider.queue(LLMProviderError("connection timeout"))
        with pytest.raises(PlannerError, match="connection timeout"):
            await planner.react_step("test", [])


# ---------------------------------------------------------------------------
# Orchestrator ReAct integration tests
# ---------------------------------------------------------------------------


class TestReactSimple:
    """Simple single-tool task: tool → final_answer."""

    @pytest.mark.asyncio
    async def test_single_tool_then_answer(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: call list_files
        # Iteration 2: final answer with results
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": "Need to see workspace",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Found README.md and src/main.py.",
                "reasoning": "Got the listing",
            }),
        ])

        run = await orch.handle_message("sess_1", "List all files")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Found README.md and src/main.py."
        assert run.iterations == 2
        # Should have 2 observations: tool + final_answer
        assert len(run.observations) == 2
        assert run.observations[0].tool == "list_files"
        assert run.observations[0].result is not None
        assert run.observations[0].result.status == "success"


class TestReactImmediateAnswer:
    """No tools needed — LLM gives final_answer immediately."""

    @pytest.mark.asyncio
    async def test_immediate_final_answer(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            _react_json({
                "action": "final_answer",
                "response": "A README is a documentation file.",
                "reasoning": "Direct knowledge",
            }),
        ])

        run = await orch.handle_message("sess_1", "What is a README?")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "A README is a documentation file."
        assert run.iterations == 1


class TestReactToolFailAdapts:
    """Tool fails → LLM adapts with different approach."""

    @pytest.mark.asyncio
    async def test_adapt_after_failure(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: read_file on nonexistent path → error
        # Iteration 2: list_files to discover what exists
        # Iteration 3: final answer
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "read_file",
                "args": {"path": "nonexistent.txt"},
                "reasoning": "Try reading the file",
            }),
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": "File not found, let me list what's available",
            }),
            _react_json({
                "action": "final_answer",
                "response": "The file nonexistent.txt doesn't exist. Available: README.md, src/main.py",
                "reasoning": "Found the actual files",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read nonexistent.txt")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.iterations == 3
        # First observation should be a failed read
        assert run.observations[0].tool == "read_file"
        assert run.observations[0].result.status == "error"
        # Second should be successful list
        assert run.observations[1].tool == "list_files"
        assert run.observations[1].result.status == "success"


class TestReactToolFailGivesUp:
    """Tool fails → LLM gives up gracefully."""

    @pytest.mark.asyncio
    async def test_gives_up_after_failure(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "read_file",
                "args": {"path": "missing.txt"},
                "reasoning": "Try reading",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Sorry, I couldn't find the file.",
                "reasoning": "File doesn't exist, no other options",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read missing.txt")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert "couldn't find" in run.final_response


class TestReactMaxIterations:
    """Max iterations reached → run fails with partial summary."""

    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        settings.react_max_iterations = 3  # Low limit for testing
        orch = Orchestrator(settings, registry)

        # Queue 3 tool actions (no final_answer) + 1 summary response
        responses = [
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": f"Iteration {i+1}",
            })
            for i in range(3)
        ]
        # The summary generation will also call the provider
        responses.append("Partial results: listed files 3 times.")
        _install_fake_provider(orch, responses)

        run = await orch.handle_message("sess_1", "Keep listing files forever")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.FAILED
        assert run.iterations == 3
        assert "maximum iterations" in run.final_response.lower()


class TestReactLoopDetection:
    """Loop detection: same tool+args repeated → blocked."""

    @pytest.mark.asyncio
    async def test_duplicate_action_blocked_after_cap(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """If the LLM calls list_files(".") 4+ times, the 4th is hard-blocked."""
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        settings.react_max_iterations = 10
        orch = Orchestrator(settings, registry)

        # Queue: 4x identical list_files (the 4th should be blocked by loop
        # detection), then the LLM gets the block error and gives final_answer.
        responses = [
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": f"Iteration {i+1}",
            })
            for i in range(5)
        ]
        responses.append(_react_json({
            "action": "final_answer",
            "response": "I was stuck in a loop, here's what I found.",
            "reasoning": "Loop detected",
        }))
        _install_fake_provider(orch, responses)

        run = await orch.handle_message("sess_1", "Analyze files")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        # Should have fewer than 10 iterations (loop was detected and broken)
        assert run.iterations <= 7
        # At least one observation should be a blocked duplicate
        blocked = [
            o for o in run.observations
            if o.result and "Blocked" in (o.result.error or "")
        ]
        assert len(blocked) >= 1, "Expected at least one blocked duplicate action"


class TestReactPolicyDenial:
    """Policy denies a tool → LLM sees denial and adapts."""

    @pytest.mark.asyncio
    async def test_path_policy_denial_continues_loop(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: try to read outside workspace → policy denial
        # Iteration 2: final answer explaining the denial
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "read_file",
                "args": {"path": "../../../etc/passwd"},
                "reasoning": "Read system file",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Can't read files outside the workspace.",
                "reasoning": "Path was denied by policy",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read /etc/passwd")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.iterations == 2
        # First observation should be a policy denial
        assert run.observations[0].tool == "read_file"
        assert run.observations[0].result.status == "denied"

    @pytest.mark.asyncio
    async def test_shell_policy_denial(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: try dangerous shell command → policy denial
        # Iteration 2: final answer
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "run_shell_safe",
                "args": {"command": "rm", "args": ["-rf", "/"], "cwd": "."},
                "reasoning": "Delete everything",
            }),
            _react_json({
                "action": "final_answer",
                "response": "That command is not allowed.",
                "reasoning": "Shell policy denied it",
            }),
        ])

        run = await orch.handle_message("sess_1", "Delete all files")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.observations[0].result.status == "denied"


class TestReactUnknownTool:
    """LLM requests a nonexistent tool → error observation, loop continues."""

    @pytest.mark.asyncio
    async def test_unknown_tool_continues(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "nonexistent_tool",
                "args": {},
                "reasoning": "Try this tool",
            }),
            _react_json({
                "action": "final_answer",
                "response": "That tool doesn't exist.",
                "reasoning": "Tool not found",
            }),
        ])

        run = await orch.handle_message("sess_1", "Use nonexistent tool")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.iterations == 2
        assert run.observations[0].result.status == "error"
        assert "Unknown tool" in run.observations[0].result.error


class TestReactValidationFailure:
    """Tool validation fails → error observation, LLM sees it."""

    @pytest.mark.asyncio
    async def test_validation_error_in_observation(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # read_file on a path that doesn't exist → tool executes but returns error
        # (read_file is safe risk, no approval needed)
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "read_file",
                "args": {"path": "does_not_exist.txt"},
                "reasoning": "Read a missing file",
            }),
            _react_json({
                "action": "final_answer",
                "response": "File not found.",
                "reasoning": "Error observed",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read does_not_exist.txt")
        run = await _wait_for_run(orch, run.run_id, timeout=15.0)

        assert run.status == RunStatus.COMPLETED
        assert run.iterations == 2
        # First observation should have an error result
        assert run.observations[0].tool == "read_file"
        assert run.observations[0].result.status == "error"


class TestReactProviderError:
    """Provider error mid-loop → run fails with partial results."""

    @pytest.mark.asyncio
    async def test_provider_error_fails_run(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: successful tool
        # Iteration 2: provider blows up
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": "List first",
            }),
            LLMProviderError("API rate limit exceeded"),
        ])

        run = await orch.handle_message("sess_1", "List files and then read them")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.FAILED
        assert run.iterations >= 1
        # Should have at least one observation from the successful first step
        assert len(run.observations) >= 1


class TestReactApprovalFlow:
    """Approval within the ReAct loop."""

    @pytest.mark.asyncio
    async def test_approval_then_execute(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: run_shell_safe (medium risk, approval required)
        # After approval: execute the tool
        # Iteration 2: final answer
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "run_shell_safe",
                "args": {"command": "pwd", "args": [], "cwd": "."},
                "reasoning": "Check working directory",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Working directory confirmed.",
                "reasoning": "Got pwd output",
            }),
        ])

        run = await orch.handle_message("sess_1", "Show me the working directory")

        # Wait for the run to reach AWAITING_APPROVAL
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.AWAITING_APPROVAL

        # Approve the step
        run = await orch.approve_step(run.run_id, "step_1", approved=True)

        # Wait for completion
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Working directory confirmed."

    @pytest.mark.asyncio
    async def test_rejection_cancels_and_compensates(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # Iteration 1: run_shell_safe → user rejects
        # Run should cancel immediately (no more LLM calls needed)
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "run_shell_safe",
                "args": {"command": "pwd", "args": [], "cwd": "."},
                "reasoning": "Check directory",
            }),
        ])

        run = await orch.handle_message("sess_1", "Run pwd")

        # Wait for AWAITING_APPROVAL
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)

        assert run.status == RunStatus.AWAITING_APPROVAL

        # Reject
        run = await orch.approve_step(run.run_id, "step_1", approved=False)

        # Wait for terminal state
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.CANCELLED
        assert "declined" in run.final_response.lower()
        # The rejection observation should be recorded
        rejected_obs = [o for o in run.observations if o.result and o.result.status == "rejected"]
        assert len(rejected_obs) == 1


class TestReactSagaCompensation:
    """Saga compensation: reject step N → undo steps 1..N-1."""

    @pytest.mark.asyncio
    async def test_reject_third_file_undoes_first_two(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Create file1, file2 (approved), then reject file3 → file1 and file2 deleted."""
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        # The LLM will ask to create 3 files one at a time.
        # We'll approve the first two, reject the third.
        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "write_file",
                "args": {"path": "file1.txt", "content": "content1", "mode": "create"},
                "reasoning": "Create first file",
            }),
            _react_json({
                "action": "tool",
                "tool": "write_file",
                "args": {"path": "file2.txt", "content": "content2", "mode": "create"},
                "reasoning": "Create second file",
            }),
            _react_json({
                "action": "tool",
                "tool": "write_file",
                "args": {"path": "file3.txt", "content": "content3", "mode": "create"},
                "reasoning": "Create third file",
            }),
        ])

        run = await orch.handle_message("sess_1", "Create three files")

        # Approve file1
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL:
                break
            await asyncio.sleep(0.1)
        assert run.status == RunStatus.AWAITING_APPROVAL
        assert any(s.step_id == "step_1" for s in run.plan.steps)
        await orch.approve_step(run.run_id, "step_1", approved=True)

        # Wait for step_2 approval (means step_1 executed)
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL and len(run.plan.steps) >= 2:
                break
            await asyncio.sleep(0.1)
        assert run.status == RunStatus.AWAITING_APPROVAL
        assert (tmp_workspace / "file1.txt").exists(), "file1.txt should exist after approval"

        # Approve file2
        await orch.approve_step(run.run_id, "step_2", approved=True)

        # Wait for step_3 approval (means step_2 executed)
        for _ in range(50):
            run = await orch.get_run(run.run_id)
            if run and run.status == RunStatus.AWAITING_APPROVAL and len(run.plan.steps) >= 3:
                break
            await asyncio.sleep(0.1)
        assert run.status == RunStatus.AWAITING_APPROVAL
        assert (tmp_workspace / "file2.txt").exists(), "file2.txt should exist after approval"

        # Reject file3
        await orch.approve_step(run.run_id, "step_3", approved=False)

        # Wait for terminal state
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.CANCELLED
        assert "rolled back" in run.final_response.lower()

        # Saga compensation should have deleted file1 and file2
        assert not (tmp_workspace / "file1.txt").exists(), "file1.txt should have been deleted by compensation"
        assert not (tmp_workspace / "file2.txt").exists(), "file2.txt should have been deleted by compensation"
        assert not (tmp_workspace / "file3.txt").exists(), "file3.txt should never have been created"


class TestReactPersistence:
    """Verify observations persist across save/load."""

    @pytest.mark.asyncio
    async def test_observations_round_trip(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": "Check workspace",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done.",
                "reasoning": "Complete",
            }),
        ])

        run = await orch.handle_message("sess_1", "List files")
        run = await _wait_for_run(orch, run.run_id)

        # Load from DB
        loaded = await orch.get_run(run.run_id)
        assert loaded is not None
        assert loaded.iterations == run.iterations
        assert loaded.max_iterations == run.max_iterations
        assert len(loaded.observations) == len(run.observations)
        assert loaded.observations[0].tool == "list_files"
        assert loaded.observations[0].result.status == "success"


class TestReactBackwardCompat:
    """use_react=False still works with the old plan-and-execute path."""

    @pytest.mark.asyncio
    async def test_legacy_path_still_works(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        await create_tables(tmp_db_path)
        settings = _make_settings(tmp_workspace, tmp_db_path)
        settings.use_react = False  # Force legacy path
        orch = Orchestrator(settings, registry)

        fake = FakeProvider()
        orch._planner = Planner(provider=fake, registry=orch._registry)
        fake.queue(json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.95,
            "reasoning": "Simple",
            "direct_response": "Legacy path works!",
            "steps": [],
        }))

        run = await orch.handle_message("sess_1", "Hello")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.final_response == "Legacy path works!"


# ---------------------------------------------------------------------------
# Model unit tests
# ---------------------------------------------------------------------------


class TestRetryPolicyModel:
    def test_defaults(self) -> None:
        rp = RetryPolicy()
        assert rp.max_retries == 0
        assert rp.backoff_base == 1.0
        assert rp.idempotent is False

    def test_custom_values(self) -> None:
        rp = RetryPolicy(max_retries=3, backoff_base=2.0, idempotent=True)
        assert rp.max_retries == 3
        assert rp.backoff_base == 2.0
        assert rp.idempotent is True


class TestObservationModel:
    def test_minimal_observation(self) -> None:
        obs = Observation(step_id="s1", iteration=1, timestamp="2025-01-01T00:00:00Z")
        assert obs.tool is None
        assert obs.result is None

    def test_full_observation(self) -> None:
        from apps.api.models.run import ToolResult
        obs = Observation(
            step_id="s1", iteration=1,
            tool="list_files", args={"path": "."},
            reasoning="Check workspace",
            result=ToolResult(tool_name="list_files", status="success",
                              input={"path": "."}, output={"files": ["a.txt"]}),
            timestamp="2025-01-01T00:00:00Z",
        )
        assert obs.tool == "list_files"
        assert obs.result.status == "success"


# ---------------------------------------------------------------------------
# Error classification tests
# ---------------------------------------------------------------------------


class TestErrorKindClassification:
    """Verify tools classify errors correctly and the executor respects them."""

    @pytest.mark.asyncio
    async def test_read_file_not_found_is_permanent(
        self, registry: SkillRegistry, tmp_workspace: Path,
    ) -> None:
        """File not found should be PERMANENT — never retried."""
        from apps.api.models.run import ErrorKind
        tool = registry.get("read_file")
        from apps.api.skills.base import ToolContext
        ctx = ToolContext(workspace_root=str(tmp_workspace), run_id="r1", step_id="s1")
        result = await tool.execute({"path": "nonexistent.txt"}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.PERMANENT

    @pytest.mark.asyncio
    async def test_write_file_already_exists_is_permanent(
        self, registry: SkillRegistry, tmp_workspace: Path,
    ) -> None:
        """Creating a file that already exists should be PERMANENT."""
        from apps.api.models.run import ErrorKind
        (tmp_workspace / "exists.txt").write_text("hello")
        tool = registry.get("write_file")
        from apps.api.skills.base import ToolContext
        ctx = ToolContext(workspace_root=str(tmp_workspace), run_id="r1", step_id="s1")
        result = await tool.execute({"path": "exists.txt", "content": "x", "mode": "create"}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.PERMANENT

    @pytest.mark.asyncio
    async def test_shell_disallowed_command_is_permanent(
        self, registry: SkillRegistry, tmp_workspace: Path,
    ) -> None:
        """Disallowed shell command should be PERMANENT."""
        from apps.api.models.run import ErrorKind
        tool = registry.get("run_shell_safe")
        from apps.api.skills.base import ToolContext
        ctx = ToolContext(workspace_root=str(tmp_workspace), run_id="r1", step_id="s1")
        result = await tool.execute({"command": "rm", "args": ["-rf", "/"], "cwd": "."}, ctx)
        assert result.status == "error"
        assert result.error_kind == ErrorKind.PERMANENT

    @pytest.mark.asyncio
    async def test_permanent_error_not_retried(
        self, registry: SkillRegistry, tmp_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Executor should NOT retry a permanent error even if retry_policy allows."""
        from apps.api.models.run import ErrorKind
        from apps.api.core.audit import AuditLogger
        from apps.api.core.executor import Executor
        from apps.api.skills.base import ToolContext
        await create_tables(tmp_db_path)

        audit = AuditLogger(tmp_db_path)
        executor = Executor(registry, audit)
        ctx = ToolContext(
            workspace_root=str(tmp_workspace), run_id="r1",
            step_id="s1", db_path=str(tmp_db_path),
        )
        # read_file has retry_policy(max_retries=1, idempotent=True)
        # but "file not found" is PERMANENT — should NOT retry
        result = await executor.execute_tool(
            "read_file", {"path": "missing.txt"}, ctx,
        )
        assert result.status == "error"
        assert result.error_kind == ErrorKind.PERMANENT
        # Check audit log — should have step_started and step_failed, but NO step_retrying
        from apps.api.database import get_connection
        conn = await get_connection(tmp_db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT event_type FROM audit_events WHERE run_id='r1' ORDER BY created_at")
            event_types = [r["event_type"] for r in rows]
        finally:
            await conn.close()
        assert "step_retrying" not in event_types, (
            f"Permanent error should not be retried, but got: {event_types}"
        )

# ---------------------------------------------------------------------------
# Batch read_file through orchestrator
# ---------------------------------------------------------------------------


class TestBatchReadFile:
    """Verify batch read_file works end-to-end through the ReAct loop."""

    @pytest.mark.asyncio
    async def test_batch_read_file_through_orchestrator(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """A batch read_file call works end-to-end through the ReAct loop."""
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "read_file",
                "args": {"paths": ["README.md", "src/main.py"]},
                "reasoning": "Reading multiple files at once",
                "user_announcement": "Let me read through those files...",
            }),
            _react_json({
                "action": "final_answer",
                "response": "I read both files successfully.",
                "reasoning": "Both files were read",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read README and main.py")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        # Should have observations: one tool call + final answer
        tool_obs = [o for o in run.observations if o.tool == "read_file"]
        assert len(tool_obs) == 1
        assert tool_obs[0].result.status == "success"
        assert tool_obs[0].result.output["files_read"] == 2

    @pytest.mark.asyncio
    async def test_batch_policy_denial(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Batch with one path outside workspace → denied."""
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "read_file",
                "args": {"paths": ["README.md", "/etc/passwd"]},
                "reasoning": "Reading files including a bad path",
                "user_announcement": "Let me read those files...",
            }),
            _react_json({
                "action": "final_answer",
                "response": "That path was denied by policy.",
                "reasoning": "Policy denied the request",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read README and /etc/passwd")
        run = await _wait_for_run(orch, run.run_id)

        # The batch should have been denied by policy
        denied_obs = [o for o in run.observations if o.result and o.result.status == "denied"]
        assert len(denied_obs) == 1
        assert "policy" in denied_obs[0].result.error.lower()


# ---------------------------------------------------------------------------
# Hybrid Plan-ReAct tests
# ---------------------------------------------------------------------------


def _make_settings_with_goals(
    workspace: Path, db_path: Path,
    use_goals: bool = True, max_replans: int = 2, max_iterations: int = 10,
) -> Settings:
    """Create settings with explicit goal/replan configuration."""
    return Settings(
        llm_provider="anthropic",
        anthropic_api_key="test-fake",
        workspace_root=workspace,
        database_path=db_path,
        use_react=True,
        react_max_iterations=max_iterations,
        react_use_goals=use_goals,
        react_max_replans=max_replans,
    )


class TestHybridPlanReact:
    """Tests for the hybrid Plan → ReAct → Replan architecture."""

    # ---- Backward Compatibility ----

    @pytest.mark.asyncio
    async def test_pure_react_when_goals_disabled(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """react_use_goals=False → no generate_goals call, no goals in prompt,
        replan action causes PlannerError."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=False)
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "explore",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "List files")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.iterations == 2
        # Verify no generate_goals call was made (only 2 calls: react_step × 2)
        assert len(fake.calls) == 2
        # Verify goals not in prompt
        for call in fake.calls:
            content = call["messages"][0].content
            assert "Goals:" not in content
            system = call.get("system", "")
            assert "GOAL TRACKING" not in system
            assert "REPLANNING" not in system
        # Verify plan has no goals
        assert run.plan.goals == []

    @pytest.mark.asyncio
    async def test_replan_action_raises_when_goals_disabled(
        self, registry: SkillRegistry,
    ) -> None:
        """With goals disabled, 'replan' action is invalid → PlannerError."""
        provider = FakeProvider()
        planner = Planner(provider=provider, registry=registry)
        provider.queue(_react_json({"action": "replan", "reasoning": "want to replan"}))
        with pytest.raises(PlannerError, match="Invalid action"):
            await planner.react_step("test", [], goals=None, enable_replan=False)

    @pytest.mark.asyncio
    async def test_goals_only_no_replan(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """use_goals=True, max_replans=0 → goals generated, but replan action invalid."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=0)
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            # 1. Goal generation
            json.dumps([
                {"goal_id": "goal_1", "description": "Explore workspace"},
                {"goal_id": "goal_2", "description": "Summarize findings"},
            ]),
            # 2. react_step → tool call
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "exploring",
                "completed_goals": ["goal_1"],
            }),
            # 3. react_step → final answer
            _react_json({
                "action": "final_answer",
                "response": "Found files", "reasoning": "done",
                "completed_goals": ["goal_2"],
            }),
        ])

        run = await orch.handle_message("sess_1", "List files")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert len(run.plan.goals) == 2
        # Goals should be tracked
        from apps.api.models.run import GoalStatus
        assert run.plan.goals[0].status == GoalStatus.DONE
        # Verify REPLANNING not in system prompt (but GOAL TRACKING is)
        for call in fake.calls[1:]:  # skip goal generation call
            system = call.get("system", "")
            assert "GOAL TRACKING" in system
            assert "REPLANNING" not in system

    # ---- Goal Checklist Tests ----

    @pytest.mark.asyncio
    async def test_goals_generated_before_loop(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """generate_goals is called before the first react_step."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            # 1. Goal generation
            json.dumps([
                {"goal_id": "goal_1", "description": "Check workspace"},
            ]),
            # 2. react_step → final answer
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "What's in the workspace?")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert len(run.plan.goals) == 1
        assert run.plan.goals[0].goal_id == "goal_1"
        assert run.plan.goals[0].description == "Check workspace"

    @pytest.mark.asyncio
    async def test_goals_included_in_react_step_prompt(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Goals checklist string appears in the LLM prompt."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "Find all files"},
                {"goal_id": "goal_2", "description": "Read the README"},
            ]),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Read workspace")
        run = await _wait_for_run(orch, run.run_id)

        # Check the react_step call (call index 1, after goal gen at index 0)
        react_call = fake.calls[1]
        content = react_call["messages"][0].content
        assert "goal_1" in content
        assert "goal_2" in content
        assert "Find all files" in content
        assert "Read the README" in content

    @pytest.mark.asyncio
    async def test_goal_sections_not_in_prompt_when_disabled(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """With goals disabled, no GOAL TRACKING or REPLANNING in system prompt."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=False)
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Hello")
        run = await _wait_for_run(orch, run.run_id)

        for call in fake.calls:
            system = call.get("system", "")
            assert "GOAL TRACKING" not in system
            assert "REPLANNING" not in system

    @pytest.mark.asyncio
    async def test_goal_status_updated_on_completion(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """LLM returns completed_goals → status is DONE."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "Check workspace"},
                {"goal_id": "goal_2", "description": "Summarize"},
            ]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "explore",
                "completed_goals": ["goal_1"],
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
                "completed_goals": ["goal_2"],
            }),
        ])

        run = await orch.handle_message("sess_1", "Explore workspace")
        run = await _wait_for_run(orch, run.run_id)

        from apps.api.models.run import GoalStatus
        assert run.plan.goals[0].status == GoalStatus.DONE
        assert run.plan.goals[1].status == GoalStatus.DONE

    @pytest.mark.asyncio
    async def test_goal_skipped(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """LLM returns skipped_goals → status is SKIPPED."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "Find tests"},
                {"goal_id": "goal_2", "description": "Run tests"},
            ]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "looking for tests",
                "skipped_goals": ["goal_2"],
                "completed_goals": ["goal_1"],
            }),
            _react_json({
                "action": "final_answer",
                "response": "No tests found", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Run tests")
        run = await _wait_for_run(orch, run.run_id)

        from apps.api.models.run import GoalStatus
        assert run.plan.goals[0].status == GoalStatus.DONE
        assert run.plan.goals[1].status == GoalStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_in_progress_marker(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """After first iteration, the first pending goal should be IN_PROGRESS."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "Step one"},
                {"goal_id": "goal_2", "description": "Step two"},
            ]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "doing step one",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Do two things")
        run = await _wait_for_run(orch, run.run_id)

        # After iter 1 (tool call), goal_1 should have been marked IN_PROGRESS
        # (and goal_2 still PENDING). After iter 2 (final_answer), the run completes.
        # We can verify the goals in the prompt of the second react_step call
        react_call_2 = fake.calls[2]  # calls: [goal_gen, react1, react2]
        content = react_call_2["messages"][0].content
        assert "→" in content  # IN_PROGRESS marker

    @pytest.mark.asyncio
    async def test_goal_generation_failure_graceful(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Goal generation failure → agent continues without goals, no crash."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            # Goal generation will get this exception
            LLMProviderError("API timeout"),
            # react_step calls
            _react_json({
                "action": "final_answer",
                "response": "Done without goals", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Hello")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.goals == []
        assert run.final_response == "Done without goals"

    @pytest.mark.asyncio
    async def test_empty_goals_for_simple_query(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """LLM returns [] for goals → no goals stored, runs as pure ReAct."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([]),  # empty goals
            _react_json({
                "action": "final_answer",
                "response": "Capital is Paris", "reasoning": "direct answer",
            }),
        ])

        run = await orch.handle_message("sess_1", "What is the capital of France?")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.goals == []

    @pytest.mark.asyncio
    async def test_goals_persisted_to_db(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Goals survive a _save_run / get_run round-trip."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(populated_workspace, tmp_db_path, use_goals=True)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "First thing"},
                {"goal_id": "goal_2", "description": "Second thing"},
            ]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "working",
                "completed_goals": ["goal_1"],
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Do things")
        run = await _wait_for_run(orch, run.run_id)

        # Re-fetch from DB
        reloaded = await orch.get_run(run.run_id)
        assert len(reloaded.plan.goals) == 2
        assert reloaded.plan.goals[0].goal_id == "goal_1"
        from apps.api.models.run import GoalStatus
        assert reloaded.plan.goals[0].status == GoalStatus.DONE

    # ---- Replanning Tests ----

    @pytest.mark.asyncio
    async def test_llm_requested_replan(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """LLM returns action=replan → replan_goals called, goals updated, loop continues."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=2)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            # 1. Goal generation
            json.dumps([
                {"goal_id": "goal_1", "description": "Explore workspace"},
                {"goal_id": "goal_2", "description": "Find tests"},
                {"goal_id": "goal_3", "description": "Run tests"},
            ]),
            # 2. react_step → tool, completes goal_1
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "exploring",
                "completed_goals": ["goal_1"],
            }),
            # 3. react_step → replan (no test files found)
            _react_json({
                "action": "replan", "reasoning": "No test files found",
                "skipped_goals": ["goal_2", "goal_3"],
            }),
            # 4. Replan goal generation
            json.dumps([
                {"goal_id": "goal_4", "description": "Read the README"},
                {"goal_id": "goal_5", "description": "Summarize project"},
            ]),
            # 5. react_step → tool with new goals
            _react_json({
                "action": "tool", "tool": "read_file",
                "args": {"path": "README.md"}, "reasoning": "reading README",
                "completed_goals": ["goal_4"],
            }),
            # 6. react_step → final answer
            _react_json({
                "action": "final_answer",
                "response": "Project is a test app", "reasoning": "done",
                "completed_goals": ["goal_5"],
            }),
        ])

        run = await orch.handle_message("sess_1", "Run the tests")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.replan_count == 1
        # Should have preserved goal_1 (DONE) and added goal_4, goal_5
        goal_ids = [g.goal_id for g in run.plan.goals]
        assert "goal_1" in goal_ids
        assert "goal_4" in goal_ids
        assert "goal_5" in goal_ids

    @pytest.mark.asyncio
    async def test_replan_preserves_completed_goals(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """After replan, completed goals are preserved, new goals appended."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "Step A"},
                {"goal_id": "goal_2", "description": "Step B"},
            ]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "step A",
                "completed_goals": ["goal_1"],
            }),
            _react_json({
                "action": "replan", "reasoning": "Step B is wrong",
                "skipped_goals": ["goal_2"],
            }),
            json.dumps([
                {"goal_id": "goal_3", "description": "Step C"},
            ]),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
                "completed_goals": ["goal_3"],
            }),
        ])

        run = await orch.handle_message("sess_1", "Do tasks")
        run = await _wait_for_run(orch, run.run_id)

        from apps.api.models.run import GoalStatus
        preserved = [g for g in run.plan.goals if g.status == GoalStatus.DONE]
        assert len(preserved) >= 1
        assert any(g.goal_id == "goal_1" for g in preserved)

    @pytest.mark.asyncio
    async def test_replan_count_increments(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """After replan, run.plan.replan_count == 1."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=2)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([{"goal_id": "goal_1", "description": "First"}]),
            _react_json({"action": "replan", "reasoning": "wrong plan"}),
            json.dumps([{"goal_id": "goal_2", "description": "Second"}]),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Task")
        run = await _wait_for_run(orch, run.run_id)

        assert run.plan.replan_count == 1

    @pytest.mark.asyncio
    async def test_replan_limit_enforced(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """max_replans=1, 2 replan requests → second returns exhausted with warning."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([{"goal_id": "goal_1", "description": "A"}]),
            # First replan — allowed
            _react_json({"action": "replan", "reasoning": "bad plan"}),
            json.dumps([{"goal_id": "goal_2", "description": "B"}]),
            # Second replan — should be rejected (limit=1)
            _react_json({"action": "replan", "reasoning": "still bad"}),
            # After exhausted, should continue with a tool or final_answer
            _react_json({
                "action": "final_answer",
                "response": "Done with limits", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Task")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.replan_count == 1  # only one replan executed

    @pytest.mark.asyncio
    async def test_auto_replan_on_majority_skipped(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """3 of 4 goals SKIPPED → auto-replan triggers."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "A"},
                {"goal_id": "goal_2", "description": "B"},
                {"goal_id": "goal_3", "description": "C"},
                {"goal_id": "goal_4", "description": "D"},
            ]),
            # Skip 3 of 4 goals in one tool call
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "checking",
                "skipped_goals": ["goal_1", "goal_2", "goal_3"],
            }),
            # Auto-replan should fire — this is the replan response
            json.dumps([
                {"goal_id": "goal_5", "description": "New plan"},
            ]),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
                "completed_goals": ["goal_5"],
            }),
        ])

        run = await orch.handle_message("sess_1", "Complex task")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.replan_count == 1

    @pytest.mark.asyncio
    async def test_auto_replan_at_halfway_with_no_progress(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Past halfway on iterations with zero goals DONE → auto-replan."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1, max_iterations=6)
        orch = Orchestrator(settings, registry)

        responses = [
            json.dumps([
                {"goal_id": "goal_1", "description": "Hard thing"},
                {"goal_id": "goal_2", "description": "Another hard thing"},
            ]),
        ]
        # 3 tool calls with no goals completed (iterations 1-3 → halfway of 6)
        for i in range(3):
            responses.append(_react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": f"path_{i}"}, "reasoning": "searching",
            }))
        # Auto-replan fires after iteration 3 (>= 6/2)
        responses.append(json.dumps([
            {"goal_id": "goal_3", "description": "Easier thing"},
        ]))
        responses.append(_react_json({
            "action": "final_answer",
            "response": "Done", "reasoning": "done",
            "completed_goals": ["goal_3"],
        }))

        _install_fake_provider(orch, responses)

        run = await orch.handle_message("sess_1", "Hard task")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.replan_count == 1

    @pytest.mark.asyncio
    async def test_no_auto_replan_when_making_progress(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Past halfway with goals DONE → no auto-replan."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1, max_iterations=6)
        orch = Orchestrator(settings, registry)

        responses = [
            json.dumps([
                {"goal_id": "goal_1", "description": "First"},
                {"goal_id": "goal_2", "description": "Second"},
                {"goal_id": "goal_3", "description": "Third"},
            ]),
        ]
        # Complete goal_1 and goal_2 before halfway
        responses.append(_react_json({
            "action": "tool", "tool": "list_files",
            "args": {"path": "."}, "reasoning": "first",
            "completed_goals": ["goal_1"],
        }))
        responses.append(_react_json({
            "action": "tool", "tool": "list_files",
            "args": {"path": "src"}, "reasoning": "second",
            "completed_goals": ["goal_2"],
        }))
        responses.append(_react_json({
            "action": "tool", "tool": "read_file",
            "args": {"path": "README.md"}, "reasoning": "third",
            "completed_goals": ["goal_3"],
        }))
        responses.append(_react_json({
            "action": "final_answer",
            "response": "All done", "reasoning": "done",
        }))

        _install_fake_provider(orch, responses)

        run = await orch.handle_message("sess_1", "Three step task")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.replan_count == 0  # No replan needed

    @pytest.mark.asyncio
    async def test_replan_disabled_via_config(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """max_replans=0 → LLM replan action treated as PlannerError, run fails."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=0)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([{"goal_id": "goal_1", "description": "A"}]),
            _react_json({"action": "replan", "reasoning": "want to replan"}),
        ])

        run = await orch.handle_message("sess_1", "Task")
        run = await _wait_for_run(orch, run.run_id)

        # replan action with enable_replan=False causes PlannerError → run fails
        assert run.status == RunStatus.FAILED
        assert "Invalid action" in (run.final_response or "")

    @pytest.mark.asyncio
    async def test_replan_failure_graceful(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """replan_goals raises exception → continues with existing goals."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=2)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([{"goal_id": "goal_1", "description": "A"}]),
            _react_json({"action": "replan", "reasoning": "bad plan"}),
            # Replan call → error (exception)
            LLMProviderError("API error during replan"),
            # Should continue — next react_step
            _react_json({
                "action": "final_answer",
                "response": "Done anyway", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Task")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        assert run.plan.goals[0].goal_id == "goal_1"

    @pytest.mark.asyncio
    async def test_observations_preserved_across_replan(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """After replan, all previous observations still visible."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([{"goal_id": "goal_1", "description": "A"}]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "first obs",
                "completed_goals": ["goal_1"],
            }),
            _react_json({"action": "replan", "reasoning": "changing plan"}),
            json.dumps([{"goal_id": "goal_2", "description": "B"}]),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "Task")
        run = await _wait_for_run(orch, run.run_id)

        # The list_files observation should still be present
        tool_obs = [o for o in run.observations if o.tool == "list_files"]
        assert len(tool_obs) == 1

    @pytest.mark.asyncio
    async def test_replan_goal_ids_continue_sequence(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """After completing goal_1 and goal_2, new goals start at goal_3."""
        await create_tables(tmp_db_path)
        settings = _make_settings_with_goals(
            populated_workspace, tmp_db_path, use_goals=True, max_replans=1)
        orch = Orchestrator(settings, registry)

        _install_fake_provider(orch, [
            json.dumps([
                {"goal_id": "goal_1", "description": "A"},
                {"goal_id": "goal_2", "description": "B"},
            ]),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "doing A",
                "completed_goals": ["goal_1", "goal_2"],
            }),
            _react_json({"action": "replan", "reasoning": "need more"}),
            # Replan returns goals with continued IDs
            json.dumps([
                {"goal_id": "goal_3", "description": "C"},
            ]),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "done",
                "completed_goals": ["goal_3"],
            }),
        ])

        run = await orch.handle_message("sess_1", "Multi-step task")
        run = await _wait_for_run(orch, run.run_id)

        goal_ids = [g.goal_id for g in run.plan.goals]
        assert "goal_1" in goal_ids
        assert "goal_3" in goal_ids


# ---------------------------------------------------------------------------
# Budget awareness tests
# ---------------------------------------------------------------------------


class TestBudgetAwareness:
    """Tests for budget-aware planning: iteration_info in prompts and warnings."""

    @pytest.mark.asyncio
    async def test_budget_info_passed_to_planner(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Verify the planner receives iteration_info with correct values."""
        await create_tables(tmp_db_path)
        settings = _make_settings(populated_workspace, tmp_db_path)
        settings = Settings(
            llm_provider="anthropic",
            anthropic_api_key="test-fake",
            workspace_root=populated_workspace,
            database_path=tmp_db_path,
            use_react=True,
            react_max_iterations=10,
            react_budget_warn_pct=30,
            react_use_goals=False,
            react_max_replans=0,
        )
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            _react_json({
                "action": "final_answer",
                "response": "Done",
                "reasoning": "immediate answer",
            }),
        ])

        run = await orch.handle_message("sess_1", "hello")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        # The planner was called once (iteration 1 of 10)
        assert len(fake.calls) >= 1
        # Check that the budget string appears in the user message
        content = fake.calls[0]["messages"][0].content
        assert "step 1 of 10" in content
        assert "9 remaining" in content

    @pytest.mark.asyncio
    async def test_budget_string_in_prompt(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """Verify the LLM prompt includes the iteration budget from step 1."""
        await create_tables(tmp_db_path)
        settings = Settings(
            llm_provider="anthropic",
            anthropic_api_key="test-fake",
            workspace_root=populated_workspace,
            database_path=tmp_db_path,
            use_react=True,
            react_max_iterations=8,
            react_budget_warn_pct=30,
            react_use_goals=False,
            react_max_replans=0,
        )
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            _react_json({
                "action": "tool",
                "tool": "list_files",
                "args": {"path": "."},
                "reasoning": "explore",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done",
                "reasoning": "done",
            }),
        ])

        run = await orch.handle_message("sess_1", "List files")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        # Step 1: "step 1 of 8 (7 remaining)"
        content_step1 = fake.calls[0]["messages"][0].content
        assert "step 1 of 8" in content_step1
        assert "7 remaining" in content_step1
        # Step 2: "step 2 of 8 (6 remaining)"
        content_step2 = fake.calls[1]["messages"][0].content
        assert "step 2 of 8" in content_step2
        assert "6 remaining" in content_step2

    @pytest.mark.asyncio
    async def test_low_budget_warning_fires(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """With max_iterations=5, budget_warn_pct=40 → warn_threshold=2.

        Step 3 of 5 has 2 remaining == warn_threshold → ⚠ should fire.
        """
        await create_tables(tmp_db_path)
        settings = Settings(
            llm_provider="anthropic",
            anthropic_api_key="test-fake",
            workspace_root=populated_workspace,
            database_path=tmp_db_path,
            use_react=True,
            react_max_iterations=5,
            react_budget_warn_pct=40,
            react_use_goals=False,
            react_max_replans=0,
        )
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "."}, "reasoning": "step1",
            }),
            _react_json({
                "action": "tool", "tool": "list_files",
                "args": {"path": "src"}, "reasoning": "step2",
            }),
            _react_json({
                "action": "final_answer",
                "response": "Done", "reasoning": "wrapping up",
            }),
        ])

        run = await orch.handle_message("sess_1", "Explore workspace")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        # warn_threshold = max(1, 5 * 40 // 100) = 2
        # Step 3 of 5: remaining = 2, which == warn_threshold → warning fires
        content_step3 = fake.calls[2]["messages"][0].content
        assert "⚠ LOW BUDGET" in content_step3

        # Steps 1 and 2 should NOT have the warning
        content_step1 = fake.calls[0]["messages"][0].content
        assert "⚠ LOW BUDGET" not in content_step1
        content_step2 = fake.calls[1]["messages"][0].content
        assert "⚠ LOW BUDGET" not in content_step2

    @pytest.mark.asyncio
    async def test_no_warning_when_budget_healthy(
        self, registry: SkillRegistry, populated_workspace: Path, tmp_db_path: Path,
    ) -> None:
        """At step 1 of 10 with 30% threshold, no warning should appear."""
        await create_tables(tmp_db_path)
        settings = Settings(
            llm_provider="anthropic",
            anthropic_api_key="test-fake",
            workspace_root=populated_workspace,
            database_path=tmp_db_path,
            use_react=True,
            react_max_iterations=10,
            react_budget_warn_pct=30,
            react_use_goals=False,
            react_max_replans=0,
        )
        orch = Orchestrator(settings, registry)

        fake = _install_fake_provider(orch, [
            _react_json({
                "action": "final_answer",
                "response": "Done",
                "reasoning": "quick answer",
            }),
        ])

        run = await orch.handle_message("sess_1", "Quick question")
        run = await _wait_for_run(orch, run.run_id)

        assert run.status == RunStatus.COMPLETED
        content = fake.calls[0]["messages"][0].content
        assert "step 1 of 10" in content
        assert "⚠ LOW BUDGET" not in content
