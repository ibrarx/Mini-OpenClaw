"""Scheduled task management endpoints: list, get, pause, resume, delete."""
import logging

from fastapi import APIRouter, HTTPException, Request

from apps.api.models.scheduled_task import TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scheduler"])


@router.get("/tasks")
async def list_tasks(
    request: Request,
    workspace_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List all scheduled tasks, optionally filtered."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return []
    task_status = TaskStatus(status) if status else None
    tasks = await scheduler.list_tasks(
        workspace_id=workspace_id, status=task_status
    )
    return [t.model_dump() for t in tasks]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    """Get a specific scheduled task."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    task = await scheduler.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task.model_dump()


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str, request: Request) -> dict:
    """Pause an active scheduled task."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    task = await scheduler.pause_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task.model_dump()


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, request: Request) -> dict:
    """Resume a paused scheduled task."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    task = await scheduler.resume_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task.model_dump()


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request) -> dict:
    """Delete a scheduled task permanently."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    deleted = await scheduler.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {"deleted": True, "task_id": task_id}


@router.get("/scheduler/health")
async def scheduler_health(request: Request) -> dict:
    """Check scheduler loop health."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return {"status": "disabled"}
    loop_alive = (
        scheduler._loop_task is not None
        and not scheduler._loop_task.done()
    )
    loop_error = None
    if scheduler._loop_task and scheduler._loop_task.done():
        exc = scheduler._loop_task.exception() if not scheduler._loop_task.cancelled() else None
        loop_error = str(exc) if exc else "cancelled"
    return {
        "status": "running" if loop_alive else "dead",
        "loop_alive": loop_alive,
        "loop_error": loop_error,
        "tasks_in_memory": len(scheduler._tasks),
        "heap_size": len(scheduler._heap),
        "inflight": len(scheduler._inflight),
        "running": scheduler._running,
    }
