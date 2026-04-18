from services.assistant.functions import (
    detect_intent,
    extract_change_component_update,
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
        return {
            "validation_errors": validation_errors,
            "final_answer": "Please correct the request details:\n- " + "\n- ".join(validation_errors),
        }

    return {
        "validation_errors": [],
        "final_answer": (
            f"{CHANGE_COMPONENT_RESPONSE} "
            f"I verified that product '{state['product_name']}', component '{state['component_name']}', "
            f"and supplier '{state['supplier_name']}' exist in the database."
        ),
    }


def ask_for_missing_node(state: AppState) -> dict:
    next_missing_field = state["missing_fields"][0]
    return {
        "validation_errors": [],
        "final_answer": FOLLOW_UP_QUESTIONS[next_missing_field],
    }


def side_question_node(state: AppState) -> dict:
    return {"final_answer": SIDE_QUESTION_RESPONSE}
