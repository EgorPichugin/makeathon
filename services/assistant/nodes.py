import json

from services.assistant.functions import (
    detect_intent,
    extract_change_component_update,
    get_filtered_products_by_route_vector,
    get_supplier_components_for_product,
    get_route_vector,
    get_product_structure,
    validate_change_request,
)
from services.assistant.prompts import (
    CHANGE_COMPONENT_RESPONSE,
    FOLLOW_UP_QUESTIONS,
    SIDE_QUESTION_RESPONSE,
)
from services.assistant.state import AppState, Intent


def orchestrator_node(state: AppState) -> dict:
    return {"intent": detect_intent(state)}


def route_after_orchestrator(state: AppState) -> str:
    intent = state["intent"]
    return intent.value if isinstance(intent, Intent) else intent


def change_component_node(state: AppState) -> dict:
    updated_state = extract_change_component_update(state)
    if updated_state["missing_fields"]:
        next_missing_field = updated_state["missing_fields"][0]
        return {
            **updated_state,
            "validation_errors": [],
            "final_answer": FOLLOW_UP_QUESTIONS[next_missing_field],
        }

    return {**updated_state, "validation_errors": []}


def route_after_change_component(state: AppState) -> str:
    return "ask_for_missing" if state.get("missing_fields") else "validator"


def validator_node(state: AppState) -> dict:
    validation_result = validate_change_request(state)
    validation_errors = validation_result["validation_errors"]

    if validation_errors:
        invalid_fields = validation_result["invalid_fields"]
        corrected_state = {
            "component_name": state.get("component_name"),
            "product_name": state.get("product_name"),
            "supplier_name": state.get("supplier_name"),
        }
        for field_name in invalid_fields:
            corrected_state[field_name] = None

        next_missing_field = invalid_fields[0]
        return {
            **corrected_state,
            "missing_fields": invalid_fields,
            "validation_errors": validation_errors,
            "final_answer": (
                "Please correct the request details:\n- "
                + "\n- ".join(validation_errors)
                + "\n\n"
                + FOLLOW_UP_QUESTIONS[next_missing_field]
            ),
        }

    return {
        "validation_errors": [],
        "missing_fields": []
    }

def suppliers_search_node(state: AppState) -> dict[str, list[str]]:
    supplier_components: dict[str, list[str]] = get_supplier_components_for_product(state["product_name"])
    
    filtered_supplier_components = get_filtered_products_by_route_vector(supplier_components, state["route_vector"])
    return {
        "final_answer": json.dumps(filtered_supplier_components, indent=2)
    }


def ask_for_missing_node(state: AppState) -> dict:
    next_missing_field = state["missing_fields"][0]
    return {
        "validation_errors": [],
        "final_answer": FOLLOW_UP_QUESTIONS[next_missing_field],
    }


def side_question_node(state: AppState) -> dict:
    return {"final_answer": SIDE_QUESTION_RESPONSE}

def create_component_structure_node(state: AppState) -> dict | None:
    route = get_route_vector(state)
    # return get_product_structure(route)

    return {"route_vector": route}
