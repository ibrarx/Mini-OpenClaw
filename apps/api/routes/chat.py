"""
POST /api/chat — Submit a user message and create a run.

Accepts a user message, creates a run through the orchestrator,
and returns the run_id with initial status. The frontend then
polls GET /api/runs/{run_id} for updates.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    session_id: str
    message: str
    workspace_id: str = "default"


class ChatResponse(BaseModel):
    """Response body for POST /api/chat."""

    run_id: str
    status: str


@router.post("/chat", response_model=ChatResponse, status_code=202)
async def submit_chat(request: ChatRequest) -> ChatResponse:
    """
    Submit a user message and create a new run.

    The orchestrator processes the message through:
    planning → policy → execution → response.
    """
    from ..core.orchestrator import Orchestrator
    from ..config import get_settings

    # Lazy singleton — avoids import-time API key requirement
    orchestrator = _get_orchestrator()

    try:
        run = await orchestrator.process_message(
            message=request.message,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
    except Exception as exc:
        logger.error("Chat processing failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(run_id=run.run_id, status=run.status.value)


# ------------------------------------------------------------------
# Orchestrator singleton
# ------------------------------------------------------------------

_orchestrator_instance: Orchestrator | None = None


def _get_orchestrator() -> "Orchestrator":
    """Get or create the singleton orchestrator."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        from ..core.orchestrator import Orchestrator
        from ..config import get_settings
        settings = get_settings()
        _orchestrator_instance = Orchestrator(settings)
    return _orchestrator_instance


def get_orchestrator() -> "Orchestrator":
    """Public accessor for other routes to share the orchestrator."""
    return _get_orchestrator()
