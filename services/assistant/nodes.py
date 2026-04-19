import json

from services.assistant.functions import (
    build_candidate_company_list,
    detect_intent,
    extract_change_component_update,
    fill_component_specs,
    format_ranking_answer,
    get_filtered_products_by_route_vector,
    get_supplier_components_for_product,
    get_route_vector,
    get_product_structure,
    list_characteristics_for_route,
    rank_component_suppliers,
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

def suppliers_search_node(state: AppState) -> dict:
    supplier_components: dict[str, list[str]] = get_supplier_components_for_product(state["product_name"])

    filtered_supplier_components = get_filtered_products_by_route_vector(supplier_components, state["route_vector"])
    return {
        "filtered_suppliers": filtered_supplier_components,
        "final_answer": json.dumps(filtered_supplier_components, indent=2),
    }


def fill_specs_node(state: AppState) -> dict:
    """Fill characteristics for the current supplier + each alternative found by suppliers_search.

    companies[0] is the current supplier (the one being replaced) — the reference for ranking.
    """
    route_vector = state.get("route_vector") or []
    characteristics = list_characteristics_for_route(route_vector)
    if not characteristics:
        # Route vector doesn't map to a known metadata schema — nothing to fill.
        return {
            "spec_matrix": None,
            "final_answer": (
                "I couldn't determine which characteristics to compare for this component type. "
                "The component's route vector did not match any known metadata schema."
            ),
        }

    current_supplier = state.get("supplier_name") or ""
    filtered = state.get("filtered_suppliers") or {}
    companies = build_candidate_company_list(current_supplier, filtered)

    if len(companies) < 2:
        return {
            "spec_matrix": None,
            "final_answer": (
                "I could not find any alternative suppliers of this component type "
                "for ranking. Only the current supplier is known."
            ),
        }

    component_name = state.get("component_name") or ""
    matrix_dict = fill_component_specs(component_name, characteristics, companies)
    return {"spec_matrix": matrix_dict}


def rank_suppliers_node(state: AppState) -> dict:
    """Run spec_ranker on the spec_filler output and format the final chat answer."""
    matrix_dict = state.get("spec_matrix")
    if not matrix_dict:
        # fill_specs_node already set a final_answer explaining why — don't override it.
        return {"ranking_result": None}

    try:
        ranking_dict = rank_component_suppliers(matrix_dict)
    except ValueError as e:
        return {
            "ranking_result": None,
            "final_answer": (
                f"I filled specifications but couldn't rank suppliers: {e}"
            ),
        }
    return {
        "ranking_result": ranking_dict,
        "final_answer": format_ranking_answer(ranking_dict),
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
