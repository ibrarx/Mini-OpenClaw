"""
POST /api/chat — Submit a user message and create a run.

Creates a run through the orchestrator and returns the run_id.
"""
from __future__ import annotations
import logging, uuid
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
from ..routes.tools import get_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

# In-memory store so the runs route can look up in-memory Run objects
_orchestrator_ref: Orchestrator | None = None

def get_last_orchestrator() -> Orchestrator | None:
    return _orchestrator_ref


@router.post("/chat", response_model=ChatResponse, status_code=202)
async def submit_chat(
    body: ChatRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> ChatResponse:
    global _orchestrator_ref
    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()

    # Ensure session
    await db.execute("INSERT OR IGNORE INTO sessions (id,created_at,updated_at) VALUES (?,?,?)",
        (body.session_id, now, now))
    msg_id = str(uuid.uuid4())
    await db.execute("INSERT INTO messages (id,session_id,role,content,created_at) VALUES (?,?,'user',?,?)",
        (msg_id, body.session_id, body.message, now))
    await db.commit()

    registry = get_registry()
    audit = AuditLogger(db)
    events = EventEmitter()
    planner = Planner(api_key=settings.anthropic_api_key, model=settings.anthropic_model, registry=registry)
    policy = PolicyEngine(workspace_root=settings.resolved_workspace)
    executor = Executor(registry=registry, audit=audit)

    orchestrator = Orchestrator(db=db, planner=planner, policy=policy, executor=executor, audit=audit, events=events)
    _orchestrator_ref = orchestrator

    run = await orchestrator.process_message(message=body.message, session_id=body.session_id, workspace_id=body.workspace_id)
    return ChatResponse(run_id=run.run_id, status=run.status.value)
