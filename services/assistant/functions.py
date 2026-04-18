from services.assistant.llm import get_structured_llm
from services.assistant.models import (
    ChangeComponentUpdateResult,
    ConversationIntentResult,
    NavigationComponentTreeResult,
)
from services.assistant.observability import invoke_with_logging
from services.assistant.prompts import (
    CHANGE_COMPONENT_UPDATE_PROMPT,
    INTENT_ROUTER_PROMPT,
    NAVIGATE_COMPONENT_TREE_REQUEST,
)
from services.assistant.state import AppState, Intent
from services.assistant.validation import validate_change_request_data

from schemas.component import (
    ConsumableIngredientMetadata,
    DimensionalNonConsumableIngredientMetadata,
    DimensionalPackagingMetadata,
    NonConsumableIngredientMetadata,
    NonDimensionalPackagingMetadata,
)


def detect_intent(state: AppState) -> Intent:
    prompt = INTENT_ROUTER_PROMPT.format(
        component_name=state.get("component_name"),
        product_name=state.get("product_name"),
        supplier_name=state.get("supplier_name"),
        missing_fields=state.get("missing_fields", []),
        user_message=state["user_message"],
    )
    result: ConversationIntentResult = invoke_with_logging(
        "detect_intent_llm",
        get_structured_llm(ConversationIntentResult),
        prompt,
    )
    return result.intent


def extract_change_component_update(state: AppState) -> dict:
    prompt = CHANGE_COMPONENT_UPDATE_PROMPT.format(
        component_name=state.get("component_name"),
        product_name=state.get("product_name"),
        supplier_name=state.get("supplier_name"),
        missing_fields=state.get("missing_fields", []),
        user_message=state["user_message"],
    )
    result: ChangeComponentUpdateResult = invoke_with_logging(
        "extract_change_component_update_llm",
        get_structured_llm(ChangeComponentUpdateResult),
        prompt,
    )
    extracted_data = result.model_dump()

    updated_state = {
        "component_name": normalize_optional_text(
            extracted_data["component_name"],
            state.get("component_name"),
        ),
        "product_name": normalize_optional_text(
            extracted_data["product_name"],
            state.get("product_name"),
        ),
        "supplier_name": normalize_optional_text(
            extracted_data["supplier_name"],
            state.get("supplier_name"),
        ),
    }
    updated_state["missing_fields"] = find_missing_fields(updated_state)
    return updated_state


def normalize_optional_text(new_value: str | None, current_value: str | None) -> str | None:
    if new_value is None:
        return current_value
    normalized = new_value.strip()
    return normalized or current_value


def find_missing_fields(data: dict) -> list[str]:
    missing_fields: list[str] = []
    if not data.get("component_name"):
        missing_fields.append("component_name")
    if not data.get("product_name"):
        missing_fields.append("product_name")
    if not data.get("supplier_name"):
        missing_fields.append("supplier_name")
    return missing_fields


def validate_change_request(state: AppState) -> dict:
    return validate_change_request_data(
        product_name=state["product_name"],
        component_name=state["component_name"],
        supplier_name=state["supplier_name"],
    )

def get_route_vector(state: AppState) -> list[int]:
    component_structure_prompt = NAVIGATE_COMPONENT_TREE_REQUEST.format(
        product_name=state.get("product_name", ""),
        component_name=state.get("component_name", ""),
        supplier_name=state.get("supplier_name", ""),
    )

    result: NavigationComponentTreeResult = invoke_with_logging(
        "navigate_component_tree_llm",
        get_structured_llm(NavigationComponentTreeResult),
        component_structure_prompt,
    )
    state["route_vector"] = result.route_vector
    return result.route_vector

def get_route_vector_for_product(supplier_name: str, component_name: str) -> list[int]:
    component_structure_prompt = NAVIGATE_COMPONENT_TREE_REQUEST.format(
        product_name="",
        component_name=component_name,
        supplier_name=supplier_name,
    )

    result: NavigationComponentTreeResult = invoke_with_logging(
        "navigate_component_tree_llm",
        get_structured_llm(NavigationComponentTreeResult),
        component_structure_prompt,
    )
    return result.route_vector

def get_product_structure(route_vector: list[int]) -> dict | None:
    if route_vector == [0, 0, 0]:
        return ConsumableIngredientMetadata().model_dump()
    elif route_vector == [0, 1, 0]:
        return NonConsumableIngredientMetadata().model_dump()
    elif route_vector == [0, 1, 1]:
        return DimensionalNonConsumableIngredientMetadata().model_dump()
    elif route_vector == [1, 0, 0]:
        return NonDimensionalPackagingMetadata().model_dump()
    elif route_vector == [1, 1, 0]:
        return DimensionalPackagingMetadata().model_dump()
    return None

def filter_products_by_route_vector(products: dict[str, list[str]], route_vector: list[int]) -> dict[str, list[str]]:
    filtered = {}
    for supplier, product_names in products.items():
        for product in product_names:
            product_vector = get_route_vector_for_product(supplier, product)
            if product_vector == route_vector: 
                if supplier not in filtered:
                    filtered[supplier] = []
                filtered[supplier].append(product)
    return filtered
