"""
Run management endpoints: list, get, approve, cancel.

Provides read access to run state and write access for approval
and cancellation actions.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_db
from ..models.run import ApprovalRequest, Run, RunStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


def _row_to_run(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a DB row to a dict suitable for JSON response."""
    d = dict(row)
    # Parse plan JSON if present
    if d.get("plan"):
        try:
            d["plan"] = json.loads(d["plan"])
        except (json.JSONDecodeError, TypeError):
            pass
    # Rename 'id' → 'run_id' to match API spec
    d["run_id"] = d.pop("id")
    return d


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return a run with its steps."""
    row = await db.execute_fetchall(
        "SELECT * FROM runs WHERE id = ?", (run_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    run = _row_to_run(row[0])

    # Attach steps
    step_rows = await db.execute_fetchall(
        "SELECT * FROM run_steps WHERE run_id = ? ORDER BY step_index",
        (run_id,),
    )
    steps = []
    for sr in step_rows:
        step = dict(sr)
        step["step_id"] = step.pop("id")
        if step.get("args"):
            try:
                step["args"] = json.loads(step["args"])
            except (json.JSONDecodeError, TypeError):
                pass
        if step.get("result"):
            try:
                step["result"] = json.loads(step["result"])
            except (json.JSONDecodeError, TypeError):
                pass
        steps.append(step)

    run["steps"] = steps
    return run


@router.get("/runs")
async def list_runs(
    session_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """List runs with optional filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if workspace_id:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])

    rows = await db.execute_fetchall(
        f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params,
    )
    return [_row_to_run(r) for r in rows]


@router.post("/runs/{run_id}/approve")
async def approve_step(
    run_id: str,
    body: ApprovalRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, str]:
    """Approve or reject a pending step."""
    # Verify run exists
    run_rows = await db.execute_fetchall(
        "SELECT * FROM runs WHERE id = ?", (run_id,)
    )
    if not run_rows:
        raise HTTPException(status_code=404, detail="Run not found")

    # Verify step exists and is awaiting approval
    step_rows = await db.execute_fetchall(
        "SELECT * FROM run_steps WHERE id = ? AND run_id = ?",
        (body.step_id, run_id),
    )
    if not step_rows:
        raise HTTPException(status_code=404, detail="Step not found")

    step = dict(step_rows[0])
    if step["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Step is not awaiting approval (current status: {step['status']})",
        )

    now = datetime.now(timezone.utc).isoformat()
    new_status = "pending" if body.approved else "skipped"

    await db.execute(
        "UPDATE run_steps SET status = ? WHERE id = ?",
        (new_status, body.step_id),
    )

    # Record approval decision
    import uuid

    await db.execute(
        """
        INSERT INTO approvals (id, run_id, step_id, payload, approved, decided_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            run_id,
            body.step_id,
            step.get("args", "{}"),
            1 if body.approved else 0,
            now,
            now,
        ),
    )
    await db.commit()

    return {"status": "approved" if body.approved else "rejected"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, str]:
    """Cancel an active run."""
    run_rows = await db.execute_fetchall(
        "SELECT * FROM runs WHERE id = ?", (run_id,)
    )
    if not run_rows:
        raise HTTPException(status_code=404, detail="Run not found")

    run = dict(run_rows[0])
    terminal = {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
    if run["status"] in terminal:
        raise HTTPException(
            status_code=409,
            detail=f"Run is already in terminal state: {run['status']}",
        )

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
        (RunStatus.CANCELLED.value, now, run_id),
    )
    await db.commit()

    return {"status": "cancelled"}
