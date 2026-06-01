"""
Tests for the structured planner — provider-agnostic.

The planner now talks to LLMs through ``LLMProvider``. We exercise it with
a tiny in-memory fake provider so tests do not depend on Anthropic, Gemini,
or any network. The behaviour under test (plan parsing, fence stripping,
defaults, error handling, summary generation) is identical to before the
provider refactor.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest

from apps.api.core.planner import Planner, PlannerError
from apps.api.providers.base import LLMMessage, LLMProvider, LLMResponse, LLMToolSchema
from apps.api.providers.errors import LLMProviderError
from apps.api.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fake provider — tiny test double that lets us script the model's output.
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    """In-memory provider used by tests. Returns canned responses per call."""

    name = "fake"

    def __init__(self, responses: list[Any] | None = None, model: str = "fake-1") -> None:
        # Each item is either a string (text) or an Exception to raise.
        self._responses: list[Any] = list(responses or [])
        self._model = model
        self.calls: list[dict[str, Any]] = []

    def queue(self, *items: Any) -> "FakeProvider":
        self._responses.extend(items)
        return self

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
        self.calls.append(
            {"messages": messages, "system": system, "tools": tools, "max_tokens": max_tokens}
        )
        if not self._responses:
            raise RuntimeError("FakeProvider has no queued response")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=str(item))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    r.discover()
    return r


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def planner(provider: FakeProvider, registry: SkillRegistry) -> Planner:
    return Planner(provider=provider, registry=registry)


# ---------------------------------------------------------------------------
# Plan creation
# ---------------------------------------------------------------------------


class TestCreatePlan:
    @pytest.mark.asyncio
    async def test_direct_answer(self, planner: Planner, provider: FakeProvider) -> None:
        provider.queue(
            json.dumps(
                {
                    "task_type": "direct_answer",
                    "confidence": 0.95,
                    "reasoning": "A README is documentation.",
                    "direct_response": "A README is a documentation file.",
                    "steps": [],
                }
            )
        )
        plan = await planner.create_plan(user_message="What is a README?")
        assert plan["task_type"] == "direct_answer"
        assert plan["direct_response"] == "A README is a documentation file."
        assert plan["steps"] == []

    @pytest.mark.asyncio
    async def test_tool_routing(self, planner: Planner, provider: FakeProvider) -> None:
        provider.queue(
            json.dumps(
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
            )
        )
        plan = await planner.create_plan(user_message="List files")
        assert plan["task_type"] == "tool_needed"
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["tool"] == "list_files"

    @pytest.mark.asyncio
    async def test_multi_step_plan(self, planner: Planner, provider: FakeProvider) -> None:
        provider.queue(
            json.dumps(
                {
                    "task_type": "multi_step",
                    "confidence": 0.85,
                    "reasoning": "read then write",
                    "steps": [
                        {"step_id": "s1", "tool": "read_file", "args": {"path": "README.md"}, "risk_level": "safe"},
                        {"step_id": "s2", "tool": "write_file",
                         "args": {"path": "n.txt", "content": "x", "mode": "create"},
                         "risk_level": "medium"},
                    ],
                }
            )
        )
        plan = await planner.create_plan(user_message="read and write")
        assert plan["task_type"] == "multi_step"
        assert len(plan["steps"]) == 2

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped(self, planner: Planner, provider: FakeProvider) -> None:
        inner = json.dumps(
            {"task_type": "direct_answer", "confidence": 0.9, "reasoning": "t", "steps": []}
        )
        provider.queue(f"```json\n{inner}\n```")
        plan = await planner.create_plan(user_message="test")
        assert plan["task_type"] == "direct_answer"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_planner_error(
        self, planner: Planner, provider: FakeProvider
    ) -> None:
        provider.queue("not json at all")
        with pytest.raises(PlannerError):
            await planner.create_plan(user_message="test")

    @pytest.mark.asyncio
    async def test_clarification_response(
        self, planner: Planner, provider: FakeProvider
    ) -> None:
        provider.queue(
            json.dumps(
                {
                    "task_type": "clarification_needed",
                    "confidence": 0.3,
                    "reasoning": "Ambiguous",
                    "direct_response": "Could you clarify?",
                    "steps": [],
                }
            )
        )
        plan = await planner.create_plan(user_message="do the thing")
        assert plan["task_type"] == "clarification_needed"
        assert plan["direct_response"] is not None

    @pytest.mark.asyncio
    async def test_defaults_applied(
        self, planner: Planner, provider: FakeProvider
    ) -> None:
        provider.queue(json.dumps({"task_type": "direct_answer"}))
        plan = await planner.create_plan(user_message="test")
        assert "confidence" in plan
        assert "reasoning" in plan
        assert "steps" in plan
        assert "direct_response" in plan

    @pytest.mark.asyncio
    async def test_confidence_passthrough(
        self, planner: Planner, provider: FakeProvider
    ) -> None:
        provider.queue(
            json.dumps(
                {"task_type": "direct_answer", "confidence": 1.5, "reasoning": "t", "steps": []}
            )
        )
        plan = await planner.create_plan(user_message="test")
        assert plan["confidence"] == 1.5

    @pytest.mark.asyncio
    async def test_provider_error_translates_to_planner_error(
        self, planner: Planner, provider: FakeProvider
    ) -> None:
        provider.queue(LLMProviderError("boom"))
        with pytest.raises(PlannerError):
            await planner.create_plan(user_message="test")

    @pytest.mark.asyncio
    async def test_no_provider_returns_friendly_message(
        self, registry: SkillRegistry
    ) -> None:
        """When no provider is configured, the planner degrades gracefully."""
        p = Planner(provider=None, registry=registry)
        plan = await p.create_plan(user_message="anything")
        assert plan["task_type"] == "direct_answer"
        assert "not configured" in plan["direct_response"].lower()


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_summary_returns_text(self, planner: Planner, provider: FakeProvider) -> None:
        provider.queue("Here is the summary.")
        result, usage = await planner.generate_summary(
            "List files", [{"tool": "list_files", "status": "success"}]
        )
        assert result == "Here is the summary."

    @pytest.mark.asyncio
    async def test_summary_handles_provider_error(
        self, planner: Planner, provider: FakeProvider
    ) -> None:
        provider.queue(LLMProviderError("API down"))
        result, usage = await planner.generate_summary("test", [])
        assert "completed" in result.lower() or "traces" in result.lower()

    @pytest.mark.asyncio
    async def test_summary_without_provider(self, registry: SkillRegistry) -> None:
        p = Planner(provider=None, registry=registry)
        result, usage = await p.generate_summary("test", [])
        assert result == "Task completed."
