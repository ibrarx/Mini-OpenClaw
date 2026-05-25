"""
Tests for sub-agent delegation — delegate_task skill and orchestrator child runs.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from apps.api.config import Settings
from apps.api.core.orchestrator import Orchestrator
from apps.api.database import create_tables, get_connection
from apps.api.models.run import RunStatus
from apps.api.providers.base import LLMMessage, LLMProvider, LLMResponse, LLMToolSchema
from apps.api.skills.registry import SkillRegistry


class FakeProvider(LLMProvider):
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


def _rj(obj: dict[str, Any]) -> str:
    return json.dumps(obj)


def _make_settings(workspace: Path, db_path: Path, **overrides: Any) -> Settings:
    defaults = dict(
        llm_provider="anthropic", anthropic_api_key="test-fake",
        workspace_root=workspace, database_path=db_path,
        use_react=True, react_max_iterations=10,
        react_use_goals=False, react_max_replans=0,
        react_self_reflect=False,
        delegate_enabled=True, delegate_max_depth=2,
        delegate_max_children=3, delegate_max_child_iterations=5,
    )
    defaults.update(overrides)
    return Settings(**defaults)


async def _build(settings: Settings, provider: FakeProvider) -> Orchestrator:
    registry = SkillRegistry()
    registry.discover(settings)
    orch = Orchestrator(settings, registry)
    from apps.api.core.planner import Planner
    orch._planner = Planner(provider, registry,
                             observation_max_chars=settings.react_observation_max_chars)
    await create_tables(settings.resolved_database)
    return orch


async def _auto_approve(orch: Orchestrator, db_path: Path):
    """Auto-approve pending steps by watching for awaiting_approval runs."""
    for _ in range(600):
        try:
            conn = await get_connection(db_path)
            try:
                # Find runs in awaiting_approval
                rows = await conn.execute_fetchall(
                    "SELECT id, plan FROM runs WHERE status = 'awaiting_approval'"
                )
                for row in rows:
                    plan_raw = row["plan"]
                    if not plan_raw:
                        continue
                    plan = json.loads(plan_raw)
                    for step in plan.get("steps", []):
                        if step.get("status") == "awaiting_approval":
                            await orch.approve_step(row["id"], step["step_id"], approved=True)
            finally:
                await conn.close()
        except Exception:
            pass
        await asyncio.sleep(0.03)


async def _run(orch: Orchestrator, settings: Settings, msg: str, ws: str = "default"):
    approver = asyncio.create_task(_auto_approve(orch, settings.resolved_database))
    try:
        run = await orch.handle_message("sess1", msg, workspace_id=ws)
        await orch.wait_pending()
        return await orch.get_run(run.run_id)
    finally:
        approver.cancel()
        try:
            await approver
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_creates_child_run(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path)
    provider = FakeProvider([
        _rj({"action": "tool", "tool": "delegate_task",
             "args": {"task": "List files"}, "reasoning": "d",
             "user_announcement": "Handing off..."}),
        _rj({"action": "final_answer", "response": "Found README.md", "reasoning": "ok"}),
        _rj({"action": "final_answer", "response": "README.md found.", "reasoning": "ok"}),
    ])
    orch = await _build(settings, provider)
    run = await _run(orch, settings, "What files?")

    assert run.status == RunStatus.COMPLETED
    assert "README" in (run.final_response or "")

    children = await orch._get_child_runs(run.run_id)
    assert len(children) == 1
    assert children[0].parent_run_id == run.run_id
    assert children[0].depth == 1
    assert children[0].status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_child_inherits_workspace(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path)
    provider = FakeProvider([
        _rj({"action": "tool", "tool": "delegate_task",
             "args": {"task": "Check"}, "reasoning": "d", "user_announcement": "d"}),
        _rj({"action": "final_answer", "response": "ok", "reasoning": "ok"}),
        _rj({"action": "final_answer", "response": "ok", "reasoning": "ok"}),
    ])
    orch = await _build(settings, provider)
    run = await _run(orch, settings, "Check", ws="myproject")

    children = await orch._get_child_runs(run.run_id)
    assert len(children) == 1
    assert children[0].workspace_id == "myproject"


@pytest.mark.asyncio
async def test_max_children_limit(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path,
                               delegate_max_children=1, react_max_iterations=15)
    provider = FakeProvider([
        _rj({"action": "tool", "tool": "delegate_task",
             "args": {"task": "A"}, "reasoning": "d", "user_announcement": "d"}),
        _rj({"action": "final_answer", "response": "A done", "reasoning": "ok"}),
        _rj({"action": "tool", "tool": "delegate_task",
             "args": {"task": "B"}, "reasoning": "d", "user_announcement": "d"}),
        _rj({"action": "final_answer", "response": "Only A.", "reasoning": "ok"}),
    ])
    orch = await _build(settings, provider)
    run = await _run(orch, settings, "A and B")

    assert run.status == RunStatus.COMPLETED
    children = await orch._get_child_runs(run.run_id)
    assert len(children) == 1


@pytest.mark.asyncio
async def test_child_iterations_capped(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path, delegate_max_child_iterations=3)
    provider = FakeProvider([
        _rj({"action": "tool", "tool": "delegate_task",
             "args": {"task": "X", "max_iterations": 10},
             "reasoning": "d", "user_announcement": "d"}),
        _rj({"action": "final_answer", "response": "ok", "reasoning": "ok"}),
        _rj({"action": "final_answer", "response": "ok", "reasoning": "ok"}),
    ])
    orch = await _build(settings, provider)
    run = await _run(orch, settings, "X")

    children = await orch._get_child_runs(run.run_id)
    assert len(children) == 1
    assert children[0].max_iterations == 3


@pytest.mark.asyncio
async def test_child_result_in_parent_observation(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path)
    provider = FakeProvider([
        _rj({"action": "tool", "tool": "delegate_task",
             "args": {"task": "Summarize"}, "reasoning": "d", "user_announcement": "d"}),
        _rj({"action": "final_answer", "response": "Summary here.", "reasoning": "ok"}),
        _rj({"action": "final_answer", "response": "Done.", "reasoning": "ok"}),
    ])
    orch = await _build(settings, provider)
    run = await _run(orch, settings, "Summarize")

    delegate_obs = [o for o in run.observations if o.tool == "delegate_task"]
    assert len(delegate_obs) == 1
    assert delegate_obs[0].result.status == "success"
    assert "child_run_id" in delegate_obs[0].result.output
    assert "Summary here." in delegate_obs[0].result.output["response"]


@pytest.mark.asyncio
async def test_delegation_disabled(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path, delegate_enabled=False)
    registry = SkillRegistry()
    registry.discover(settings)
    assert registry.get("delegate_task") is None
    assert registry.get("list_files") is not None


@pytest.mark.asyncio
async def test_child_registry_restrictions(tmp_workspace: Path, tmp_db_path: Path):
    settings = _make_settings(tmp_workspace, tmp_db_path)
    registry = SkillRegistry()
    registry.discover(settings, is_child_run=True)
    assert registry.get("delegate_task") is None
    assert registry.get("remember_fact") is None
    assert registry.get("list_files") is not None
    assert registry.get("write_file") is not None
