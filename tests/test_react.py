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
    )


def _install_fake_provider(orch: Orchestrator, responses: list[Any]) -> FakeProvider:
    fake = FakeProvider(responses)
    orch._planner = Planner(provider=fake, registry=orch._registry)
    return fake


async def _wait_for_run(orch: Orchestrator, run_id: str, timeout: float = 10.0) -> Any:
    """Poll until the run reaches a terminal state."""
    for _ in range(int(timeout / 0.1)):
        run = await orch.get_run(run_id)
        if run and run.status in (
            RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED,
        ):
            return run
        await asyncio.sleep(0.1)
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
