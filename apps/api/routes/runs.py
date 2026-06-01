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


class ClarifyRequest(BaseModel):
    answer: str


class ClarificationSettingsResponse(BaseModel):
    enabled: bool
    threshold: float
    max_rounds: int


class ClarificationSettingsUpdate(BaseModel):
    enabled: bool | None = None
    threshold: float | None = None
    max_rounds: int | None = None


@router.get("/settings/clarification", response_model=ClarificationSettingsResponse)
async def get_clarification_settings(request: Request) -> ClarificationSettingsResponse:
    """Return current clarification gate settings."""
    settings = request.app.state.orchestrator._settings
    return ClarificationSettingsResponse(
        enabled=settings.clarification_enabled,
        threshold=settings.clarification_threshold,
        max_rounds=settings.clarification_max_rounds,
    )


@router.patch("/settings/clarification", response_model=ClarificationSettingsResponse)
async def update_clarification_settings(
    body: ClarificationSettingsUpdate, request: Request,
) -> ClarificationSettingsResponse:
    """Update clarification gate settings at runtime (in-memory, not persisted to .env)."""
    settings = request.app.state.orchestrator._settings
    if body.enabled is not None:
        object.__setattr__(settings, "clarification_enabled", body.enabled)
    if body.threshold is not None:
        clamped = max(0.0, min(1.0, body.threshold))
        object.__setattr__(settings, "clarification_threshold", clamped)
    if body.max_rounds is not None:
        clamped = max(0, min(5, body.max_rounds))
        object.__setattr__(settings, "clarification_max_rounds", clamped)
    logger.info(
        "Clarification settings updated: enabled=%s threshold=%.2f max_rounds=%d",
        settings.clarification_enabled, settings.clarification_threshold,
        settings.clarification_max_rounds,
    )
    return ClarificationSettingsResponse(
        enabled=settings.clarification_enabled,
        threshold=settings.clarification_threshold,
        max_rounds=settings.clarification_max_rounds,
    )


@router.post("/runs/{run_id}/clarify")
async def clarify_run(run_id: str, body: ClarifyRequest, request: Request) -> dict:
    """Submit a clarification answer for a run awaiting clarification."""
    orchestrator = request.app.state.orchestrator
    if not body.answer.strip():
        raise HTTPException(status_code=400, detail="Answer cannot be empty")
    try:
        run = await orchestrator.provide_clarification(run_id, body.answer.strip())
        return run.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Clarification failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


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


@router.get("/runs/{run_id}/explain")
async def explain_run(run_id: str, request: Request, detail_level: str = "summary") -> dict:
    """Generate a causal explanation of why the agent made each decision."""
    from apps.api.config import get_settings
    from apps.api.skills.base import ToolContext
    from apps.api.skills.explain_run import ExplainRunTool

    settings = get_settings()
    tool = ExplainRunTool()
    ctx = ToolContext(
        workspace_root=str(settings.resolved_workspace),
        run_id=run_id,
        db_path=str(settings.resolved_database),
    )
    result = await tool.execute(
        {"run_id": run_id, "detail_level": detail_level}, ctx
    )
    if result.status == "error":
        raise HTTPException(status_code=404, detail=result.error or "Unknown error")
    return result.model_dump()


@router.get("/usage/summary")
async def usage_summary(request: Request, session_id: str | None = None) -> dict:
    """Return aggregated token usage and cost across runs.

    If ``session_id`` is given, scope to that session. Otherwise, all runs.
    Returns per-model split, total tokens, total cost, dream usage, and the
    pricing verification date.
    """
    from apps.api.core.token_utils import PRICING_LAST_VERIFIED
    from apps.api.database import get_connection
    from apps.api.config import get_settings

    orchestrator = request.app.state.orchestrator
    runs = await orchestrator.list_runs(session_id=session_id, limit=500)

    totals: dict[str, float] = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "cost_usd": 0.0, "llm_calls": 0,
    }
    by_model: dict[str, dict[str, float]] = {}
    by_phase: dict[str, int] = {}
    has_estimates = False
    run_count = 0

    for r in runs:
        u = r.usage
        if u.llm_calls == 0:
            continue
        run_count += 1
        totals["input_tokens"] += u.input_tokens
        totals["output_tokens"] += u.output_tokens
        totals["cache_read_tokens"] += u.cache_read_tokens
        totals["cache_write_tokens"] += u.cache_write_tokens
        totals["cost_usd"] += u.cost_usd
        totals["llm_calls"] += u.llm_calls
        if u.has_estimates:
            has_estimates = True

        model_key = u.model or r.model_name or "unknown"
        if model_key not in by_model:
            by_model[model_key] = {
                "input_tokens": 0, "output_tokens": 0,
                "cost_usd": 0.0, "llm_calls": 0, "provider": u.provider or "",
            }
        by_model[model_key]["input_tokens"] += u.input_tokens
        by_model[model_key]["output_tokens"] += u.output_tokens
        by_model[model_key]["cost_usd"] += u.cost_usd
        by_model[model_key]["llm_calls"] += u.llm_calls

        for phase, tokens in u.by_phase.items():
            by_phase[phase] = by_phase.get(phase, 0) + tokens

    # Dream usage — aggregated from dream_usage table
    dream_totals = {
        "input_tokens": 0, "output_tokens": 0,
        "cost_usd": 0.0, "dream_cycles": 0,
    }
    try:
        settings = get_settings()
        conn = await get_connection(settings.resolved_database)
        try:
            rows = await conn.execute_fetchall(
                "SELECT input_tokens, output_tokens, cost_usd FROM dream_usage"
            )
            for row in rows:
                dream_totals["input_tokens"] += row["input_tokens"]
                dream_totals["output_tokens"] += row["output_tokens"]
                dream_totals["cost_usd"] += row["cost_usd"]
                dream_totals["dream_cycles"] += 1
        finally:
            await conn.close()
    except Exception:
        pass  # Table might not exist on old DBs

    # Add dream tokens into totals
    totals["input_tokens"] += dream_totals["input_tokens"]
    totals["output_tokens"] += dream_totals["output_tokens"]
    totals["cost_usd"] += dream_totals["cost_usd"]
    totals["llm_calls"] += dream_totals["dream_cycles"]
    if dream_totals["dream_cycles"] > 0:
        by_phase["dream"] = dream_totals["input_tokens"] + dream_totals["output_tokens"]

    return {
        "session_id": session_id,
        "run_count": run_count,
        "totals": totals,
        "by_model": by_model,
        "by_phase": by_phase,
        "dream": dream_totals,
        "has_estimates": has_estimates,
        "pricing_last_verified": PRICING_LAST_VERIFIED,
    }


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    """SSE endpoint that streams run status updates in real-time."""
    orchestrator = request.app.state.orchestrator

    # Verify the run exists
    run = await orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    async def event_generator():
        """Yield SSE-formatted events.

        Subscribe BEFORE checking current state so that events emitted
        between the state check and the first queue.get() are captured.
        This prevents a race where fast-completing runs finish before
        the subscription is active.
        """
        # Subscribe first — any events emitted from this point are queued
        queue = event_emitter.subscribe(run_id)
        try:
            # Now fetch the current state (after subscribing)
            current_run = await orchestrator.get_run(run_id)
            if current_run is None:
                yield f"event: error\ndata: {{\"message\": \"Run not found\"}}\n\n"
                return

            # If already terminal, send final state and close
            if current_run.status.value in TERMINAL_STATUSES:
                run_data = json.dumps(current_run.model_dump(), default=str)
                yield f"event: {current_run.status.value}\ndata: {run_data}\n\n"
                return

            # Send the current state as the initial event
            run_data = json.dumps(current_run.model_dump(), default=str)
            yield f"event: initial\ndata: {run_data}\n\n"

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
