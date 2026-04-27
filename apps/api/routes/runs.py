"""Run management endpoints: list, get, approve, cancel."""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from apps.api.models.run import Run

router = APIRouter(tags=["runs"])

class ApproveRequest(BaseModel):
    step_id: str
    approved: bool

@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    run = await orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run.model_dump()

@router.get("/runs")
async def list_runs(request: Request, session_id: str | None = None,
                     workspace_id: str | None = None, status: str | None = None,
                     limit: int = 50, offset: int = 0) -> list[dict]:
    orchestrator = request.app.state.orchestrator
    runs = await orchestrator.list_runs(session_id=session_id, workspace_id=workspace_id,
                                         status=status, limit=limit, offset=offset)
    return [r.model_dump() for r in runs]

@router.post("/runs/{run_id}/approve")
async def approve_step(run_id: str, body: ApproveRequest, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    run = await orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if run.status.value in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Run already in terminal state: {run.status.value}")
    updated = await orchestrator.approve_step(run_id, body.step_id, body.approved)
    if updated is None:
        raise HTTPException(status_code=404, detail="Run not found after approval")
    return updated.model_dump()

@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    run = await orchestrator.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run.model_dump()
