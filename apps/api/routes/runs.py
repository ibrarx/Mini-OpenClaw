"""
Run management endpoints: list, get, approve, cancel.
"""
from __future__ import annotations
import json, logging, uuid
from datetime import datetime, timezone
from typing import Any
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from ..database import get_db
from ..models.run import ApprovalRequest, RunStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


def _row_to_run(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("plan"):
        try: d["plan"] = json.loads(d["plan"])
        except (json.JSONDecodeError, TypeError): pass
    d["run_id"] = d.pop("id")
    return d


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    row = await db.execute_fetchall("SELECT * FROM runs WHERE id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    run = _row_to_run(row[0])
    step_rows = await db.execute_fetchall("SELECT * FROM run_steps WHERE run_id = ? ORDER BY step_index", (run_id,))
    steps = []
    for sr in step_rows:
        step = dict(sr); step["step_id"] = step.pop("id")
        if step.get("args"):
            try: step["args"] = json.loads(step["args"])
            except: pass
        if step.get("result"):
            try: step["result"] = json.loads(step["result"])
            except: pass
        steps.append(step)
    run["steps"] = steps
    return run


@router.get("/runs")
async def list_runs(
    session_id: str | None = Query(None), workspace_id: str | None = Query(None),
    status: str | None = Query(None), limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0), db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if session_id: clauses.append("session_id = ?"); params.append(session_id)
    if workspace_id: clauses.append("workspace_id = ?"); params.append(workspace_id)
    if status: clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    rows = await db.execute_fetchall(f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params)
    return [_row_to_run(r) for r in rows]


@router.post("/runs/{run_id}/approve")
async def approve_step(run_id: str, body: ApprovalRequest, db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    """Approve or reject a pending step. If approved, resume execution."""
    from .chat import get_last_orchestrator
    orch = get_last_orchestrator()

    # Check if orchestrator has this run in-memory (still awaiting)
    if orch and run_id in orch._runs:
        try:
            run = await orch.approve_step(run_id, body.step_id, body.approved, db=db)
            # Re-fetch from DB for consistent response
            return await get_run(run_id, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Fallback: DB-only approval (run not in memory — just record the decision)
    run_rows = await db.execute_fetchall("SELECT * FROM runs WHERE id = ?", (run_id,))
    if not run_rows:
        raise HTTPException(status_code=404, detail="Run not found")
    step_rows = await db.execute_fetchall("SELECT * FROM run_steps WHERE id = ? AND run_id = ?", (body.step_id, run_id))
    if not step_rows:
        raise HTTPException(status_code=404, detail="Step not found")
    step = dict(step_rows[0])
    if step["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"Step not awaiting approval (status: {step['status']})")
    now = datetime.now(timezone.utc).isoformat()
    new_status = "pending" if body.approved else "skipped"
    await db.execute("UPDATE run_steps SET status = ? WHERE id = ?", (new_status, body.step_id))
    await db.execute(
        "INSERT INTO approvals (id,run_id,step_id,payload,approved,decided_at,created_at) VALUES (?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), run_id, body.step_id, step.get("args","{}"), 1 if body.approved else 0, now, now))
    await db.commit()
    return {"status": "approved" if body.approved else "rejected"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db: aiosqlite.Connection = Depends(get_db)) -> dict[str, str]:
    run_rows = await db.execute_fetchall("SELECT * FROM runs WHERE id = ?", (run_id,))
    if not run_rows:
        raise HTTPException(status_code=404, detail="Run not found")
    run = dict(run_rows[0])
    terminal = {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
    if run["status"] in terminal:
        raise HTTPException(status_code=409, detail=f"Run already terminal: {run['status']}")
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("UPDATE runs SET status=?, updated_at=? WHERE id=?", (RunStatus.CANCELLED.value, now, run_id))
    await db.commit()
    return {"status": "cancelled"}
