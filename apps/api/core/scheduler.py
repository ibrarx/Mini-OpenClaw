"""core/scheduler — Heap-based task scheduler with SQLite persistence.

Uses a min-heap keyed on ``next_run_at`` to fire tasks at the right
moment via ``asyncio.call_later``.  Tasks that require LLM execution are
dispatched via ``orchestrator.handle_message()`` (fire-and-forget).
Completion is tracked by polling the resulting run's status on the next
scheduler tick.

Design choices (see discussion with Ali):
  - Option B (#1): heap-based, not polling — precise timing, zero idle overhead.
  - Option B (#2): fire-and-forget via handle_message, track completion later.
  - C+D (#3): approval at schedule-creation time (the skill is approval_required);
    runtime approval goes through normal queue and SSE events notify the UI.
  - Option C (#4): scheduler injected into ToolContext via ``schedule_fn``.
"""
from __future__ import annotations

import asyncio
import heapq
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite

from apps.api.database import get_connection
from apps.api.models.scheduled_task import ScheduleType, ScheduledTask, TaskStatus

if TYPE_CHECKING:
    from apps.api.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Background task scheduler backed by SQLite with an in-memory heap."""

    def __init__(
        self,
        db_path: Path,
        orchestrator: "Orchestrator",
        *,
        max_tasks: int = 20,
    ) -> None:
        self._db_path = db_path
        self._orchestrator = orchestrator
        self._max_tasks = max_tasks

        # Min-heap of (next_run_at_iso, task_id) for O(1) next-due lookup
        self._heap: list[tuple[str, str]] = []
        # task_id → ScheduledTask for quick lookup
        self._tasks: dict[str, ScheduledTask] = {}
        # task_id → run_id for in-flight tracking
        self._inflight: dict[str, str] = {}

        self._running = False
        self._wake_event = asyncio.Event()
        self._loop_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load tasks from DB, build the heap, and start the scheduler loop."""
        await self._load_from_db()
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info(
            "Task scheduler started — %d active task(s) in heap", len(self._heap)
        )

    async def stop(self) -> None:
        """Gracefully stop the scheduler loop."""
        self._running = False
        self._wake_event.set()  # unblock the sleep
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("Task scheduler stopped")

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Sleep until the next task is due, execute it, repeat."""
        logger.info("Scheduler loop started")
        while self._running:
            try:
                # Check in-flight runs from previous cycle
                await self._check_inflight()

                # Determine how long to sleep
                sleep_for = self._seconds_until_next()

                if sleep_for is None:
                    if self._inflight:
                        # Tasks are in-flight but nothing in the heap —
                        # poll every 5s to detect completion and reschedule.
                        logger.debug(
                            "Scheduler: heap empty, %d in-flight — polling in 5s",
                            len(self._inflight),
                        )
                        self._wake_event.clear()
                        try:
                            await asyncio.wait_for(
                                self._wake_event.wait(), timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue
                    else:
                        # No tasks at all — wait until woken by a new task creation
                        logger.debug("Scheduler: no tasks in heap, waiting for wake event")
                        self._wake_event.clear()
                        await self._wake_event.wait()
                        logger.debug("Scheduler: woken by new task")
                        continue

                if sleep_for > 0:
                    # If there are in-flight tasks, cap sleep to 5s for
                    # faster completion detection.
                    if self._inflight:
                        sleep_for = min(sleep_for, 5.0)
                    logger.debug("Scheduler: sleeping %.1fs until next task", sleep_for)
                    self._wake_event.clear()
                    try:
                        await asyncio.wait_for(
                            self._wake_event.wait(), timeout=sleep_for
                        )
                        logger.debug("Scheduler: woken early by new task")
                    except asyncio.TimeoutError:
                        pass  # normal — sleep elapsed

                # Fire all due tasks
                await self._fire_due_tasks()

                # Safeguard: if active tasks exist but heap is empty
                # (all entries were stale/popped), rebuild the heap so
                # tasks don't get orphaned.
                if not self._heap and not self._inflight:
                    active = [
                        t for t in self._tasks.values()
                        if t.status == TaskStatus.ACTIVE
                    ]
                    if active:
                        for t in active:
                            heapq.heappush(self._heap, (t.next_run_at, t.id))
                        logger.warning(
                            "Scheduler: rebuilt heap with %d orphaned active task(s)",
                            len(active),
                        )

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Scheduler loop error: %s", exc, exc_info=True)
                await asyncio.sleep(5)  # back off on unexpected errors
        logger.info("Scheduler loop exited")

    def _seconds_until_next(self) -> float | None:
        """Seconds until the next due task, or None if the heap is empty."""
        while self._heap:
            next_at_str, task_id = self._heap[0]
            task = self._tasks.get(task_id)
            # Skip stale heap entries
            if task is None or task.status != TaskStatus.ACTIVE:
                heapq.heappop(self._heap)
                continue
            if task.next_run_at != next_at_str:
                # Stale entry — the task's next_run_at was updated
                heapq.heappop(self._heap)
                continue
            try:
                next_at = datetime.fromisoformat(next_at_str)
                if next_at.tzinfo is None:
                    next_at = next_at.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                diff = (next_at - now).total_seconds()
                return max(0.0, diff)
            except (ValueError, TypeError):
                heapq.heappop(self._heap)
                continue
        return None

    async def _fire_due_tasks(self) -> None:
        """Pop and execute all tasks whose next_run_at <= now."""
        now = datetime.now(timezone.utc)
        fired_count = 0
        while self._heap:
            next_at_str, task_id = self._heap[0]
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.ACTIVE:
                heapq.heappop(self._heap)
                continue
            if task.next_run_at != next_at_str:
                heapq.heappop(self._heap)
                continue

            try:
                next_at = datetime.fromisoformat(next_at_str)
                if next_at.tzinfo is None:
                    next_at = next_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                heapq.heappop(self._heap)
                continue

            if next_at > now:
                break  # remaining tasks are in the future

            heapq.heappop(self._heap)

            # Don't fire if already in-flight
            if task_id in self._inflight:
                logger.debug("Scheduler: task %s already in-flight, skipping", task_id)
                continue

            logger.info("Scheduler: firing task %s ('%s')", task_id, task.message[:60])
            await self._execute_task(task)
            fired_count += 1

        if fired_count:
            logger.info("Scheduler: fired %d task(s) this cycle", fired_count)

    async def _execute_task(self, task: ScheduledTask) -> None:
        """Fire-and-forget: create a run via the orchestrator."""
        # Determine which tools are pre-approved for this run
        pre_approved: list[str] = []
        if task.pre_approved_tools:
            if task.schedule_type == ScheduleType.ONCE:
                # One-time tasks always use pre-approval
                pre_approved = task.pre_approved_tools
            elif task.approve_all_runs:
                # Recurring task with blanket approval — every run is pre-approved
                pre_approved = task.pre_approved_tools
            # else: approve_all_runs=False → no pre-approval, user approves each run

        try:
            run = await self._orchestrator.handle_message(
                session_id=f"scheduled_{task.id}",
                message=task.message,
                workspace_id=task.workspace_id,
                is_scheduled=True,
                pre_approved_tools=pre_approved,
            )
            self._inflight[task.id] = run.run_id
            logger.info(
                "Scheduled task %s fired → run %s (pre_approved=%s)",
                task.id, run.run_id, pre_approved,
            )
        except Exception as exc:
            logger.error("Failed to fire scheduled task %s: %s", task.id, exc)
            now_str = datetime.now(timezone.utc).isoformat()
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            task.updated_at = now_str
            self._tasks[task.id] = task
            await self._save_task(task)

    async def _check_inflight(self) -> None:
        """Check in-flight runs and update task records on completion."""
        completed_ids: list[str] = []
        for task_id, run_id in list(self._inflight.items()):
            task = self._tasks.get(task_id)
            if task is None:
                completed_ids.append(task_id)
                continue
            try:
                run = await self._orchestrator.get_run(run_id)
                if run is None:
                    completed_ids.append(task_id)
                    continue
                status = run.status.value
                if status in ("completed", "failed", "cancelled"):
                    completed_ids.append(task_id)
                    now_str = datetime.now(timezone.utc).isoformat()
                    task.run_count += 1
                    task.last_run_at = now_str
                    task.last_run_id = run_id
                    task.updated_at = now_str

                    if status in ("failed", "cancelled"):
                        task.error = run.final_response or f"Run {status}"
                    else:
                        task.error = None

                    if task.schedule_type == ScheduleType.ONCE:
                        task.status = TaskStatus.COMPLETED
                    elif task.max_runs > 0 and task.run_count >= task.max_runs:
                        task.status = TaskStatus.COMPLETED
                    else:
                        # Schedule next interval run
                        interval = task.interval_seconds or 60
                        next_at = datetime.now(timezone.utc) + timedelta(
                            seconds=interval
                        )
                        task.next_run_at = next_at.isoformat()
                        heapq.heappush(
                            self._heap, (task.next_run_at, task.id)
                        )

                    self._tasks[task.id] = task
                    await self._save_task(task)
                    logger.info(
                        "Scheduled task %s run completed (status=%s, count=%d)",
                        task.id, status, task.run_count,
                    )
            except Exception as exc:
                logger.warning(
                    "Error checking inflight task %s: %s", task_id, exc
                )

        for tid in completed_ids:
            self._inflight.pop(tid, None)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_task(
        self,
        session_id: str,
        message: str,
        *,
        workspace_id: str = "default",
        delay_minutes: int = 0,
        interval_minutes: int = 0,
        max_runs: int = 0,
        pre_approved_tools: list[str] | None = None,
        approve_all_runs: bool = False,
    ) -> ScheduledTask:
        """Create a new scheduled task and push it onto the heap."""
        # Enforce max active tasks
        active_count = sum(
            1 for t in self._tasks.values() if t.status == TaskStatus.ACTIVE
        )
        if active_count >= self._max_tasks:
            raise ValueError(
                f"Maximum active tasks ({self._max_tasks}) reached. "
                "Pause or delete existing tasks first."
            )

        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        task_id = f"task_{uuid.uuid4().hex[:12]}"

        if interval_minutes > 0:
            schedule_type = ScheduleType.INTERVAL
            interval_seconds = interval_minutes * 60
            next_run_at = now + timedelta(minutes=delay_minutes or interval_minutes)
        else:
            schedule_type = ScheduleType.ONCE
            interval_seconds = None
            next_run_at = now + timedelta(minutes=max(delay_minutes, 1))

        task = ScheduledTask(
            id=task_id,
            workspace_id=workspace_id,
            session_id=session_id,
            message=message,
            schedule_type=schedule_type,
            run_at=next_run_at.isoformat() if schedule_type == ScheduleType.ONCE else None,
            interval_seconds=interval_seconds,
            next_run_at=next_run_at.isoformat(),
            status=TaskStatus.ACTIVE,
            created_at=now_str,
            updated_at=now_str,
            max_runs=max_runs,
            pre_approved_tools=pre_approved_tools or [],
            approve_all_runs=approve_all_runs,
        )

        self._tasks[task.id] = task
        heapq.heappush(self._heap, (task.next_run_at, task.id))
        try:
            await self._save_task(task)
        except Exception as exc:
            # Roll back in-memory state on DB failure
            self._tasks.pop(task.id, None)
            # Can't easily remove from heap, but stale entries are
            # cleaned lazily in _seconds_until_next / _fire_due_tasks
            raise ValueError(f"Failed to persist task: {exc}") from exc
        self._wake_event.set()  # wake the loop to recalculate sleep

        logger.info(
            "Created scheduled task %s: type=%s, next_run=%s, delay=%.0fs",
            task.id, task.schedule_type.value, task.next_run_at,
            (next_run_at - now).total_seconds(),
        )
        return task

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    async def list_tasks(
        self,
        *,
        workspace_id: str | None = None,
        status: TaskStatus | None = None,
    ) -> list[ScheduledTask]:
        """List tasks with optional filters."""
        tasks = list(self._tasks.values())
        if workspace_id:
            tasks = [t for t in tasks if t.workspace_id == workspace_id]
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    async def pause_task(self, task_id: str) -> ScheduledTask | None:
        """Pause an active task."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status != TaskStatus.ACTIVE:
            return task
        task.status = TaskStatus.PAUSED
        task.updated_at = datetime.now(timezone.utc).isoformat()
        self._tasks[task.id] = task
        await self._save_task(task)
        logger.info("Paused scheduled task %s", task_id)
        return task

    async def resume_task(self, task_id: str) -> ScheduledTask | None:
        """Resume a paused task."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status != TaskStatus.PAUSED:
            return task

        now = datetime.now(timezone.utc)
        task.status = TaskStatus.ACTIVE
        task.updated_at = now.isoformat()

        # If next_run_at is in the past, reschedule to now + interval (or now for once)
        try:
            next_at = datetime.fromisoformat(task.next_run_at)
            if next_at.tzinfo is None:
                next_at = next_at.replace(tzinfo=timezone.utc)
            if next_at < now:
                if task.schedule_type == ScheduleType.INTERVAL and task.interval_seconds:
                    task.next_run_at = (
                        now + timedelta(seconds=task.interval_seconds)
                    ).isoformat()
                else:
                    task.next_run_at = (now + timedelta(seconds=30)).isoformat()
        except (ValueError, TypeError):
            task.next_run_at = (now + timedelta(seconds=30)).isoformat()

        self._tasks[task.id] = task
        heapq.heappush(self._heap, (task.next_run_at, task.id))
        await self._save_task(task)
        self._wake_event.set()
        logger.info("Resumed scheduled task %s, next run at %s", task_id, task.next_run_at)
        return task

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task permanently."""
        task = self._tasks.pop(task_id, None)
        if task is None:
            return False
        self._inflight.pop(task_id, None)
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                "DELETE FROM scheduled_tasks WHERE id = ?", (task_id,)
            )
            await conn.commit()
        finally:
            await conn.close()
        logger.info("Deleted scheduled task %s", task_id)
        return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _save_task(self, task: ScheduledTask) -> None:
        """Upsert a task into SQLite."""
        conn = await get_connection(self._db_path)
        try:
            await conn.execute(
                """INSERT INTO scheduled_tasks
                   (id, workspace_id, session_id, message, schedule_type,
                    run_at, interval_seconds, last_run_at, next_run_at,
                    status, created_at, updated_at, run_count, max_runs,
                    last_run_id, error, pre_approved_tools, approve_all_runs)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     workspace_id=excluded.workspace_id,
                     session_id=excluded.session_id,
                     message=excluded.message,
                     schedule_type=excluded.schedule_type,
                     run_at=excluded.run_at,
                     interval_seconds=excluded.interval_seconds,
                     last_run_at=excluded.last_run_at,
                     next_run_at=excluded.next_run_at,
                     status=excluded.status,
                     updated_at=excluded.updated_at,
                     run_count=excluded.run_count,
                     max_runs=excluded.max_runs,
                     last_run_id=excluded.last_run_id,
                     error=excluded.error,
                     pre_approved_tools=excluded.pre_approved_tools,
                     approve_all_runs=excluded.approve_all_runs
                """,
                (
                    task.id, task.workspace_id, task.session_id, task.message,
                    task.schedule_type.value, task.run_at, task.interval_seconds,
                    task.last_run_at, task.next_run_at, task.status.value,
                    task.created_at, task.updated_at, task.run_count,
                    task.max_runs, task.last_run_id, task.error,
                    json.dumps(task.pre_approved_tools),
                    1 if task.approve_all_runs else 0,
                ),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def _load_from_db(self) -> None:
        """Load active/paused tasks from SQLite and rebuild the heap."""
        conn = await get_connection(self._db_path)
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM scheduled_tasks WHERE status IN ('active', 'paused')"
            )
        finally:
            await conn.close()

        self._tasks.clear()
        self._heap.clear()

        for row in rows:
            task = self._row_to_task(row)
            self._tasks[task.id] = task
            if task.status == TaskStatus.ACTIVE:
                heapq.heappush(self._heap, (task.next_run_at, task.id))

        logger.info(
            "Loaded %d scheduled tasks from database (%d active in heap)",
            len(self._tasks),
            len(self._heap),
        )

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> ScheduledTask:
        """Convert a database row to a ScheduledTask model."""
        # Deserialize pre_approved_tools from JSON string
        raw_tools = row["pre_approved_tools"]
        try:
            pre_approved = json.loads(raw_tools) if raw_tools else []
        except (json.JSONDecodeError, TypeError):
            pre_approved = []

        return ScheduledTask(
            id=row["id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            message=row["message"],
            schedule_type=ScheduleType(row["schedule_type"]),
            run_at=row["run_at"],
            interval_seconds=row["interval_seconds"],
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            run_count=row["run_count"],
            max_runs=row["max_runs"],
            last_run_id=row["last_run_id"],
            error=row["error"],
            pre_approved_tools=pre_approved,
            approve_all_runs=bool(row["approve_all_runs"]),
        )
