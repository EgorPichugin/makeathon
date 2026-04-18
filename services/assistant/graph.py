from langgraph.graph import END, START, StateGraph

from services.assistant.nodes import (
    ask_for_missing_node,
    change_component_node,
    orchestrator_node,
    route_after_change_component,
    route_after_orchestrator,
    side_question_node,
    validator_node,
    create_component_structure_node,
)
from services.assistant.observability import logged_node
from services.assistant.state import AppState


def build_orchestrator_graph():
    graph = StateGraph(AppState)

    #region Nodes
    
    # User intention detection
    graph.add_node("orchestrator", logged_node("orchestrator", orchestrator_node))

    # Retrieve entered parameters and track missing information
    graph.add_node("change_component", logged_node("change_component", change_component_node))

    # Ask for missing information if any required details are not provided
    graph.add_node("ask_for_missing", logged_node("ask_for_missing", ask_for_missing_node))

    # Handle side questions that are not related to change component requests
    graph.add_node("side_question", logged_node("side_question", side_question_node))

    # Validate the change component request against the database and provide a final answer
    graph.add_node("validator", logged_node("validator", validator_node))
    #endregion

    # Nodes for createng a BaseModel Shema for the given component
    graph.add_node("create_component_structure", logged_node("create_component_structure", create_component_structure_node))

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "change_component": "change_component",
            "side_question": "side_question",
        },
    )
    graph.add_conditional_edges(
        "change_component",
        route_after_change_component,
        {
            "ask_for_missing": "ask_for_missing",
            "validator": "validator",
        },
    )

    graph.add_edge("ask_for_missing", END)
    graph.add_edge("side_question", END)
    graph.add_edge("validator", "create_component_structure")
    graph.add_edge("create_component_structure", END)

    return graph.compile()

def save_orchestrator_graph(graph):
    png_bytes = graph.get_graph().draw_mermaid_png()
    with open("langgraph_structure.png", "wb") as f:
        f.write(png_bytes)

orchestrator_graph = build_orchestrator_graph()
save_orchestrator_graph(orchestrator_graph)
