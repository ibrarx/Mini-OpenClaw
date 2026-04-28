"""POST /api/chat — Submit a user message and create a run."""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["chat"])

class ChatRequest(BaseModel):
    session_id: str
    message: str
    workspace_id: str = "default"

class ChatResponse(BaseModel):
    run_id: str
    status: str

@router.post("/chat", response_model=ChatResponse, status_code=202)
async def submit_chat(body: ChatRequest, request: Request) -> ChatResponse:
    orchestrator = request.app.state.orchestrator
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        run = await orchestrator.handle_message(
            session_id=body.session_id, message=body.message.strip(),
            workspace_id=body.workspace_id)
        return ChatResponse(run_id=run.run_id, status=run.status.value)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
