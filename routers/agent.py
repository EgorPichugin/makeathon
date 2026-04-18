from fastapi import APIRouter

from core.config import ASSISTANT_DB_PATH
from schemas.agent import AgentRequest, AgentResponse
from services.assistant.graph import orchestrator_graph
from services.assistant.observability import invoke_with_logging
from services.assistant.storage import load_thread_state, save_thread_state


router = APIRouter(prefix="/agent", tags=["agent"])

@router.post("/request", response_model=AgentResponse)
def handle_agent_request(payload: AgentRequest) -> AgentResponse:
    state = load_thread_state(payload.thread_id, ASSISTANT_DB_PATH)
    result = invoke_with_logging(
        "orchestrator_graph",
        orchestrator_graph,
        {**state, "user_message": payload.message},
    )
    save_thread_state(payload.thread_id, result, ASSISTANT_DB_PATH)
    return AgentResponse(answer=result["final_answer"])
