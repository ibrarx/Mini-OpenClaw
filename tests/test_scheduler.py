"""Tests for the task scheduler — heap-based scheduling with SQLite persistence."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.core.scheduler import TaskScheduler
from apps.api.database import create_tables
from apps.api.models.scheduled_task import ScheduleType, ScheduledTask, TaskStatus
from apps.api.models.run import Run, RunStatus


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    """Create a temporary database with all tables."""
    path = tmp_path / "test_scheduler.db"
    await create_tables(path)
    return path


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator with handle_message and get_run."""
    orch = AsyncMock()
    orch.handle_message = AsyncMock(return_value=Run(
        run_id="run_test123",
        session_id="test",
        workspace_id="default",
        status=RunStatus.COMPLETED,
        user_message="test task",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    ))
    orch.get_run = AsyncMock(return_value=Run(
        run_id="run_test123",
        session_id="test",
        workspace_id="default",
        status=RunStatus.COMPLETED,
        user_message="test task",
        final_response="Done",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    ))
    return orch


@pytest.fixture
async def scheduler(db_path: Path, mock_orchestrator) -> TaskScheduler:
    """Create a scheduler instance (not started)."""
    return TaskScheduler(db_path, mock_orchestrator, max_tasks=5)


# ------------------------------------------------------------------
# Task CRUD
# ------------------------------------------------------------------

class TestTaskCRUD:
    @pytest.mark.asyncio
    async def test_create_one_time_task(self, scheduler: TaskScheduler):
        task = await scheduler.create_task(
            session_id="sess1",
            message="Check workspace files",
            delay_minutes=5,
        )
        assert task.id.startswith("task_")
        assert task.schedule_type == ScheduleType.ONCE
        assert task.status == TaskStatus.ACTIVE
        assert task.interval_seconds is None
        assert task.run_count == 0

    @pytest.mark.asyncio
    async def test_create_interval_task(self, scheduler: TaskScheduler):
        task = await scheduler.create_task(
            session_id="sess1",
            message="Scan for changes",
            interval_minutes=10,
            max_runs=5,
        )
        assert task.schedule_type == ScheduleType.INTERVAL
        assert task.interval_seconds == 600
        assert task.max_runs == 5

    @pytest.mark.asyncio
    async def test_get_task(self, scheduler: TaskScheduler):
        task = await scheduler.create_task(
            session_id="sess1", message="test", delay_minutes=5
        )
        fetched = await scheduler.get_task(task.id)
        assert fetched is not None
        assert fetched.id == task.id
        assert fetched.message == "test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, scheduler: TaskScheduler):
        result = await scheduler.get_task("task_doesnotexist")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_tasks(self, scheduler: TaskScheduler):
        await scheduler.create_task(session_id="s1", message="t1", delay_minutes=5)
        await scheduler.create_task(session_id="s1", message="t2", delay_minutes=10)
        tasks = await scheduler.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_status(self, scheduler: TaskScheduler):
        t1 = await scheduler.create_task(session_id="s1", message="t1", delay_minutes=5)
        await scheduler.create_task(session_id="s1", message="t2", delay_minutes=10)
        await scheduler.pause_task(t1.id)
        active = await scheduler.list_tasks(status=TaskStatus.ACTIVE)
        paused = await scheduler.list_tasks(status=TaskStatus.PAUSED)
        assert len(active) == 1
        assert len(paused) == 1

    @pytest.mark.asyncio
    async def test_max_tasks_enforced(self, scheduler: TaskScheduler):
        # max_tasks=5 in fixture
        for i in range(5):
            await scheduler.create_task(session_id="s1", message=f"t{i}", delay_minutes=5)
        with pytest.raises(ValueError, match="Maximum active tasks"):
            await scheduler.create_task(session_id="s1", message="too many", delay_minutes=5)


# ------------------------------------------------------------------
# Pause / Resume / Delete
# ------------------------------------------------------------------

class TestTaskLifecycle:
    @pytest.mark.asyncio
    async def test_pause_and_resume(self, scheduler: TaskScheduler):
        task = await scheduler.create_task(
            session_id="s1", message="test", delay_minutes=5
        )
        paused = await scheduler.pause_task(task.id)
        assert paused is not None
        assert paused.status == TaskStatus.PAUSED

        resumed = await scheduler.resume_task(task.id)
        assert resumed is not None
        assert resumed.status == TaskStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_pause_nonexistent(self, scheduler: TaskScheduler):
        result = await scheduler.pause_task("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_nonexistent(self, scheduler: TaskScheduler):
        result = await scheduler.resume_task("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_task(self, scheduler: TaskScheduler):
        task = await scheduler.create_task(
            session_id="s1", message="doomed", delay_minutes=5
        )
        assert await scheduler.delete_task(task.id) is True
        assert await scheduler.get_task(task.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, scheduler: TaskScheduler):
        assert await scheduler.delete_task("nope") is False


# ------------------------------------------------------------------
# Execution
# ------------------------------------------------------------------

class TestTaskExecution:
    @pytest.mark.asyncio
    async def test_execute_fires_handle_message(self, scheduler: TaskScheduler, mock_orchestrator):
        task = await scheduler.create_task(
            session_id="s1", message="List workspace files", delay_minutes=0
        )
        await scheduler._execute_task(task)

        mock_orchestrator.handle_message.assert_called_once()
        call_kwargs = mock_orchestrator.handle_message.call_args
        assert call_kwargs.kwargs["message"] == "List workspace files"
        assert call_kwargs.kwargs["is_scheduled"] is True
        assert task.id in scheduler._inflight

    @pytest.mark.asyncio
    async def test_check_inflight_completes_once_task(
        self, scheduler: TaskScheduler, mock_orchestrator
    ):
        task = await scheduler.create_task(
            session_id="s1", message="one-time task", delay_minutes=0
        )
        # Simulate in-flight
        scheduler._inflight[task.id] = "run_test123"

        await scheduler._check_inflight()

        updated = await scheduler.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.run_count == 1
        assert updated.last_run_id == "run_test123"
        assert task.id not in scheduler._inflight

    @pytest.mark.asyncio
    async def test_check_inflight_reschedules_interval_task(
        self, scheduler: TaskScheduler, mock_orchestrator
    ):
        task = await scheduler.create_task(
            session_id="s1",
            message="recurring",
            interval_minutes=5,
        )
        scheduler._inflight[task.id] = "run_test123"

        await scheduler._check_inflight()

        updated = await scheduler.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.ACTIVE
        assert updated.run_count == 1
        # Next run should be ~5 minutes from now
        next_at = datetime.fromisoformat(updated.next_run_at)
        if next_at.tzinfo is None:
            next_at = next_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        assert (next_at - now).total_seconds() > 200  # ~5 min, allow slack

    @pytest.mark.asyncio
    async def test_max_runs_completes_interval_task(
        self, scheduler: TaskScheduler, mock_orchestrator
    ):
        task = await scheduler.create_task(
            session_id="s1",
            message="limited recurring",
            interval_minutes=5,
            max_runs=1,
        )
        scheduler._inflight[task.id] = "run_test123"

        await scheduler._check_inflight()

        updated = await scheduler.get_task(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.run_count == 1


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

class TestPersistence:
    @pytest.mark.asyncio
    async def test_reload_from_db(self, db_path: Path, mock_orchestrator):
        # Create with one scheduler instance
        s1 = TaskScheduler(db_path, mock_orchestrator, max_tasks=10)
        await s1.create_task(session_id="s1", message="persisted", delay_minutes=5)
        await s1.create_task(session_id="s1", message="persisted2", interval_minutes=10)

        # Load in a fresh scheduler instance
        s2 = TaskScheduler(db_path, mock_orchestrator, max_tasks=10)
        await s2._load_from_db()

        tasks = await s2.list_tasks()
        assert len(tasks) == 2
        assert any(t.message == "persisted" for t in tasks)
        assert any(t.message == "persisted2" for t in tasks)


# ------------------------------------------------------------------
# Heap mechanics
# ------------------------------------------------------------------

class TestHeapMechanics:
    @pytest.mark.asyncio
    async def test_seconds_until_next_empty(self, scheduler: TaskScheduler):
        assert scheduler._seconds_until_next() is None

    @pytest.mark.asyncio
    async def test_seconds_until_next_future(self, scheduler: TaskScheduler):
        await scheduler.create_task(
            session_id="s1", message="future", delay_minutes=10
        )
        secs = scheduler._seconds_until_next()
        assert secs is not None
        assert secs > 500  # ~10 min

    @pytest.mark.asyncio
    async def test_seconds_until_next_past(self, scheduler: TaskScheduler):
        task = await scheduler.create_task(
            session_id="s1", message="overdue", delay_minutes=1
        )
        # Manually set next_run_at to the past
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        task.next_run_at = past
        scheduler._tasks[task.id] = task
        import heapq
        heapq.heappush(scheduler._heap, (past, task.id))

        secs = scheduler._seconds_until_next()
        assert secs is not None
        assert secs == 0.0
