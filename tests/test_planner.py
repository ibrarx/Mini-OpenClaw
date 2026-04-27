"""
Tests for the structured planner with mocked Claude API.

Covers plan parsing, validation, retry logic, PlannerResponse,
risk level parsing, replan_after_step, and direct_response.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.core.planner import (
    CompletedStep,
    Planner,
    PlannerError,
    PlannerResponse,
    _parse_risk,
)
from apps.api.models.run import Plan, TaskType
from apps.api.models.step import RiskLevel, RunStep
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def planner(registry):
    p = Planner(api_key="test-fake", model="test", registry=registry)
    # Zero out backoff for fast tests
    p.BACKOFF_BASE = 0.0
    return p


def _mock_response(text: str):
    """Build a mock Anthropic API response with the given text."""
    cb = MagicMock()
    cb.text = text
    r = MagicMock()
    r.content = [cb]
    return r


# ---------------------------------------------------------------------------
# Risk-level helper
# ---------------------------------------------------------------------------

class TestParseRisk:
    def test_safe(self):
        assert _parse_risk("safe") == RiskLevel.SAFE

    def test_medium(self):
        assert _parse_risk("medium") == RiskLevel.MEDIUM

    def test_high(self):
        assert _parse_risk("high") == RiskLevel.HIGH

    def test_unknown_defaults_safe(self):
        assert _parse_risk("extreme") == RiskLevel.SAFE

    def test_none_defaults_safe(self):
        assert _parse_risk(None) == RiskLevel.SAFE


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_direct_answer(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.95,
            "reasoning": "A README is documentation.",
            "direct_response": "A README is a documentation file.",
            "steps": [],
        }))
        assert p.task_type == TaskType.DIRECT_ANSWER
        assert p.direct_response == "A README is a documentation file."
        assert len(p.steps) == 0

    def test_tool_needed_with_risk(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.9,
            "reasoning": "list files",
            "direct_response": None,
            "steps": [{
                "step_id": "s1",
                "tool": "list_files",
                "args": {"path": "."},
                "risk_level": "safe",
                "reasoning": "List workspace contents",
            }],
        }))
        assert p.task_type == TaskType.TOOL_NEEDED
        assert p.steps[0].tool == "list_files"
        assert p.steps[0].risk_level == RiskLevel.SAFE

    def test_multi_step(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "multi_step",
            "confidence": 0.85,
            "reasoning": "read then summarise",
            "direct_response": None,
            "steps": [
                {"step_id": "s1", "tool": "read_file", "args": {"path": "README.md"}, "risk_level": "safe"},
                {"step_id": "s2", "tool": "write_file", "args": {"path": "notes.txt", "content": "summary", "mode": "create"}, "risk_level": "medium"},
            ],
        }))
        assert p.task_type == TaskType.MULTI_STEP
        assert len(p.steps) == 2
        assert p.steps[1].risk_level == RiskLevel.MEDIUM

    def test_markdown_fences(self, planner):
        raw = "```json\n" + json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.9,
            "reasoning": "test",
            "steps": [],
        }) + "\n```"
        p = planner._parse_plan(raw)
        assert p.task_type == TaskType.DIRECT_ANSWER

    def test_confidence_clamped_high(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "direct_answer",
            "confidence": 1.5,
            "reasoning": "t",
            "steps": [],
        }))
        assert p.confidence == 1.0

    def test_confidence_clamped_low(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "direct_answer",
            "confidence": -0.5,
            "reasoning": "t",
            "steps": [],
        }))
        assert p.confidence == 0.0

    def test_missing_step_id_auto_generated(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.9,
            "reasoning": "x",
            "steps": [{"tool": "list_files", "args": {"path": "."}}],
        }))
        assert p.steps[0].step_id == "step_1"

    def test_direct_answer_fallback(self, planner):
        """direct_answer field is also accepted as legacy format."""
        p = planner._parse_plan(json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.9,
            "reasoning": "x",
            "direct_answer": "legacy answer",
            "steps": [],
        }))
        assert p.direct_response == "legacy answer"

    def test_clarification_needed(self, planner):
        p = planner._parse_plan(json.dumps({
            "task_type": "clarification_needed",
            "confidence": 0.3,
            "reasoning": "Ambiguous request",
            "direct_response": "Could you clarify which file?",
            "steps": [],
        }))
        assert p.task_type == TaskType.CLARIFICATION_NEEDED
        assert p.direct_response is not None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_tool(self, planner):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            steps=[RunStep(step_id="s1", tool="list_files", args={"path": "."})],
        )
        planner._validate_plan(plan)  # should not raise

    def test_unknown_tool_raises(self, planner):
        plan = Plan(
            task_type=TaskType.TOOL_NEEDED,
            confidence=0.9,
            steps=[RunStep(step_id="s1", tool="hack_system", args={})],
        )
        with pytest.raises(ValueError, match="unknown tool"):
            planner._validate_plan(plan)

    def test_all_seven_tools_accepted(self, planner):
        tools = [
            "list_files", "read_file", "write_file", "search_in_files",
            "run_shell_safe", "remember_fact", "search_memory",
        ]
        for tool_name in tools:
            plan = Plan(
                task_type=TaskType.TOOL_NEEDED,
                confidence=0.9,
                steps=[RunStep(step_id="s1", tool=tool_name, args={})],
            )
            planner._validate_plan(plan)  # should not raise


# ---------------------------------------------------------------------------
# Full flow with mocked API
# ---------------------------------------------------------------------------

class TestCreatePlan:
    @pytest.mark.asyncio
    async def test_direct_answer_returns_planner_response(self, planner):
        raw = json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.95,
            "reasoning": "A README is documentation.",
            "direct_response": "A README is documentation.",
            "steps": [],
        })
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(
            return_value=_mock_response(raw)
        )

        resp = await planner.create_plan("What is a README?")
        assert isinstance(resp, PlannerResponse)
        assert resp.plan.task_type == TaskType.DIRECT_ANSWER
        assert resp.raw_model_output == raw

    @pytest.mark.asyncio
    async def test_tool_routing(self, planner):
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(
            return_value=_mock_response(json.dumps({
                "task_type": "tool_needed",
                "confidence": 0.9,
                "reasoning": "list",
                "steps": [{"step_id": "s1", "tool": "list_files", "args": {"path": "."}, "risk_level": "safe"}],
            }))
        )
        resp = await planner.create_plan("List files")
        assert resp.plan.steps[0].tool == "list_files"
        assert resp.plan.steps[0].risk_level == RiskLevel.SAFE

    @pytest.mark.asyncio
    async def test_invalid_json_retries_and_fails(self, planner):
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(
            return_value=_mock_response("not json at all")
        )
        with pytest.raises(PlannerError, match="3 attempts"):
            await planner.create_plan("test")

    @pytest.mark.asyncio
    async def test_no_api_key_returns_stub(self):
        p = Planner(api_key="", model="test")
        resp = await p.create_plan("hello")
        assert resp.plan.task_type == TaskType.DIRECT_ANSWER
        assert resp.raw_model_output == "(no api key)"

    @pytest.mark.asyncio
    async def test_memory_context_included(self, planner):
        """Verify memory context is passed through to the API call."""
        raw = json.dumps({
            "task_type": "direct_answer",
            "confidence": 0.9,
            "reasoning": "x",
            "steps": [],
        })
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(
            return_value=_mock_response(raw)
        )

        await planner.create_plan(
            "test",
            context={"memory_context": "user likes dark mode"},
        )

        # Check that the user content contains memory
        call_args = planner._client.messages.create.call_args
        user_msg = call_args.kwargs["messages"][0]["content"]
        assert "dark mode" in user_msg


# ---------------------------------------------------------------------------
# Replan
# ---------------------------------------------------------------------------

class TestReplan:
    @pytest.mark.asyncio
    async def test_replan_returns_response(self, planner):
        raw = json.dumps({
            "task_type": "tool_needed",
            "confidence": 0.85,
            "reasoning": "write summary",
            "steps": [{"step_id": "s2", "tool": "write_file", "args": {"path": "notes.txt", "content": "done", "mode": "create"}, "risk_level": "medium"}],
        })
        planner._client = MagicMock()
        planner._client.messages = MagicMock()
        planner._client.messages.create = AsyncMock(
            return_value=_mock_response(raw)
        )

        completed = [
            CompletedStep(
                step=RunStep(step_id="s1", tool="read_file", args={"path": "README.md"}),
                result={"content": "hello world"},
            )
        ]
        remaining = [
            RunStep(step_id="s2", tool="write_file", args={"path": "notes.txt", "content": "?", "mode": "create"}),
        ]

        resp = await planner.replan_after_step(
            original_message="Read README and summarise it",
            completed_steps=completed,
            remaining_steps=remaining,
        )
        assert isinstance(resp, PlannerResponse)
        assert resp.plan.steps[0].tool == "write_file"

    @pytest.mark.asyncio
    async def test_replan_no_api_key(self):
        p = Planner(api_key="", model="test")
        resp = await p.replan_after_step("msg", [], [])
        assert resp.plan.task_type == TaskType.DIRECT_ANSWER
