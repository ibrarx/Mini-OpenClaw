"""
Run management endpoints: list, get, approve, cancel.

These endpoints let the frontend track run progress, display plans,
handle approval flows, and cancel active runs.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])


class ApproveRequest(BaseModel):
    """Request body for POST /api/runs/{run_id}/approve."""

    step_id: str
    approved: bool


@router.get("/runs")
async def list_runs(
    session_id: str | None = Query(None),
    workspace_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List runs with optional session/workspace filters."""
    from .chat import get_orchestrator
    orchestrator = get_orchestrator()
    runs = orchestrator.list_runs(
        session_id=session_id,
        workspace_id=workspace_id,
        limit=limit,
    )
    return [_run_to_dict(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Return current run status, steps, approvals, and outputs."""
    from .chat import get_orchestrator
    orchestrator = get_orchestrator()
    run = orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return _run_to_dict(run)


@router.post("/runs/{run_id}/approve")
async def approve_step(run_id: str, request: ApproveRequest) -> dict[str, Any]:
    """
    Approve or reject a pending action.

    If approved, the orchestrator resumes execution from the
    approved step. If rejected, the run is cancelled.
    """
    from .chat import get_orchestrator
    orchestrator = get_orchestrator()

    try:
        run = await orchestrator.approve_step(
            run_id=run_id,
            step_id=request.step_id,
            approved=request.approved,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Approval failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return _run_to_dict(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    """Cancel an active run."""
    from .chat import get_orchestrator
    orchestrator = get_orchestrator()
    run = orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    from ..models.run import RunStatus
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        raise HTTPException(status_code=400, detail=f"Run already in terminal state: {run.status.value}")

    run.status = RunStatus.CANCELLED
    run.final_response = "Run cancelled by user."
    return _run_to_dict(run)


def _run_to_dict(run) -> dict[str, Any]:
    """Serialise a Run to a JSON-compatible dict."""
    data = run.model_dump()
    # Ensure enum values are strings
    data["status"] = run.status.value
    if run.plan:
        data["plan"]["task_type"] = run.plan.task_type.value
        for step in data["plan"]["steps"]:
            if hasattr(step.get("status"), "value"):
                pass  # Already a string from model_dump
    return data
