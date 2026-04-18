from fastapi import APIRouter

from schemas.agent import AgentRequest, AgentResponse
from schemas.route_vector import RouteVectorRequest, RouteVectorResponse
from services.assistant.functions import get_product_structure, get_route_vector
from services.assistant.graph import orchestrator_graph
from services.assistant.observability import invoke_with_logging
from services.assistant.storage import load_thread_state, save_thread_state


router = APIRouter(prefix="/agent", tags=["agent"])

@router.post("/request", response_model=AgentResponse)
def handle_agent_request(payload: AgentRequest) -> AgentResponse:
    state = load_thread_state(payload.thread_id)
    result = invoke_with_logging(
        "orchestrator_graph",
        orchestrator_graph,
        {**state, "user_message": payload.message},
    )
    save_thread_state(payload.thread_id, result)
    return AgentResponse(answer=result["final_answer"])

@router.post("/route-vector", response_model=RouteVectorResponse)
def route_vector_test(payload: RouteVectorRequest) -> RouteVectorResponse:
    state = {
        "component_name": payload.component_name,
        "product_name": payload.product_name,
        "supplier_name": payload.supplier_name,
    }
    route_vector = get_route_vector(state)
    return RouteVectorResponse(
        route_vector=route_vector,
        product_structure=get_product_structure(route_vector),
    )
