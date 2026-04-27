"""
POST /api/chat — Submit a user message and create a run.

Creates a run record in SQLite and returns the run_id. In T02 the
orchestrator is a stub; the full pipeline will be wired in T04.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends

from ..config import get_settings
from ..core.audit import AuditLogger
from ..core.events import EventEmitter
from ..core.executor import Executor
from ..core.orchestrator import Orchestrator
from ..core.planner import Planner
from ..core.policy import PolicyEngine
from ..database import get_db
from ..models.run import ChatRequest, ChatResponse, RunStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse, status_code=202)
async def submit_chat(
    body: ChatRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> ChatResponse:
    """Accept a user message and create a new run.

    Returns 202 Accepted with the run_id and initial status.
    """
    settings = get_settings()

    # Ensure session exists
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT OR IGNORE INTO sessions (id, created_at, updated_at)
        VALUES (?, ?, ?)
        """,
        (body.session_id, now, now),
    )

    # Store the user message
    msg_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO messages (id, session_id, role, content, created_at)
        VALUES (?, ?, 'user', ?, ?)
        """,
        (msg_id, body.session_id, body.message, now),
    )
    await db.commit()

    # Wire up orchestrator with stubs
    audit = AuditLogger(db)
    events = EventEmitter()
    planner = Planner(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
    )
    policy = PolicyEngine(workspace_root=settings.resolved_workspace)
    executor = Executor()

    orchestrator = Orchestrator(
        db=db,
        planner=planner,
        policy=policy,
        executor=executor,
        audit=audit,
        events=events,
    )

    run = await orchestrator.process_message(
        message=body.message,
        session_id=body.session_id,
        workspace_id=body.workspace_id,
    )

    return ChatResponse(run_id=run.run_id, status=run.status.value)
