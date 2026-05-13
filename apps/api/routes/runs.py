"""Run management endpoints: list, get, approve, cancel, and SSE stream."""
import asyncio
import json
import logging

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from apps.api.core.events import event_emitter
from apps.api.models.run import Run

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])

TERMINAL_EVENTS = {"run_completed", "run_failed", "run_cancelled"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
HEARTBEAT_INTERVAL = 15  # seconds


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


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    """SSE endpoint that streams run status updates in real-time."""
    orchestrator = request.app.state.orchestrator

    # Verify the run exists
    run = await orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    async def event_generator():
        """Yield SSE-formatted events."""
        # If the run is already terminal, send current state and close
        if run.status.value in TERMINAL_STATUSES:
            run_data = json.dumps(run.model_dump(), default=str)
            yield f"event: {run.status.value}\ndata: {run_data}\n\n"
            return

        # Send the current state as the initial event
        run_data = json.dumps(run.model_dump(), default=str)
        yield f"event: initial\ndata: {run_data}\n\n"

        # Subscribe to future events
        queue = event_emitter.subscribe(run_id)
        try:
            while True:
                try:
                    # Wait for next event with heartbeat timeout
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    # Check if client disconnected
                    if await request.is_disconnected():
                        logger.debug("SSE client disconnected for run %s", run_id)
                        return
                    continue

                event_type = event["event_type"]

                # Fetch the latest run state from the orchestrator
                current_run = await orchestrator.get_run(run_id)
                if current_run is None:
                    yield f"event: error\ndata: {{\"message\": \"Run not found\"}}\n\n"
                    return

                run_data = json.dumps(current_run.model_dump(), default=str)
                yield f"event: {event_type}\ndata: {run_data}\n\n"

                # Close stream on terminal events
                if event_type in TERMINAL_EVENTS:
                    return

        except asyncio.CancelledError:
            logger.debug("SSE stream cancelled for run %s", run_id)
        finally:
            event_emitter.unsubscribe(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind proxy
        },
    )
