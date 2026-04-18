import sqlite3
from pathlib import Path

from services.assistant.llm import get_structured_llm
from services.assistant.models import (
    ChangeComponentUpdateResult,
    ConversationIntentResult,
)
from services.assistant.observability import invoke_with_logging
from services.assistant.prompts import (
    CHANGE_COMPONENT_UPDATE_PROMPT,
    INTENT_ROUTER_PROMPT,
)
from services.assistant.state import AppState, Intent


CPG_DB_PATH = Path(r"C:\Users\pichu\Documents\repos\hackaton\db.sqlite")


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
    validation_errors: list[str] = []

    with sqlite3.connect(CPG_DB_PATH) as connection:
        product_id = _get_product_id_by_sku(connection, state["product_name"])
        component_id = _get_product_id_by_sku(connection, state["component_name"])
        supplier_id = _get_supplier_id_by_name(connection, state["supplier_name"])

        if product_id is None:
            validation_errors.append(
                f"Product '{state['product_name']}' was not found in Product.SKU."
            )
        if component_id is None:
            validation_errors.append(
                f"Component '{state['component_name']}' was not found in Product.SKU."
            )
        if supplier_id is None:
            validation_errors.append(
                f"Supplier '{state['supplier_name']}' was not found in Supplier.Name."
            )
        if validation_errors:
            return {"validation_errors": validation_errors}

        if not _component_belongs_to_product(connection, product_id, component_id):
            validation_errors.append(
                f"Component '{state['component_name']}' is not a BOM component of product '{state['product_name']}'."
            )
        if not _supplier_supplies_product(connection, supplier_id, component_id):
            validation_errors.append(
                f"Supplier '{state['supplier_name']}' does not supply raw material '{state['component_name']}'."
            )
        if _supplier_supplies_product(connection, supplier_id, product_id):
            validation_errors.append(
                f"Supplier '{state['supplier_name']}' already supplies finished good '{state['product_name']}', which is not allowed by this rule."
            )

    return {"validation_errors": validation_errors}


def _value_exists(connection: sqlite3.Connection, query: str, value: str) -> bool:
    row = connection.execute(query, (value.strip(),)).fetchone()
    return row is not None


def _get_product_id_by_sku(connection: sqlite3.Connection, sku: str) -> int | None:
    row = connection.execute(
        "SELECT Id FROM Product WHERE LOWER(SKU) = LOWER(?) LIMIT 1",
        (sku.strip(),),
    ).fetchone()
    return row[0] if row else None


def _get_supplier_id_by_name(connection: sqlite3.Connection, supplier_name: str) -> int | None:
    row = connection.execute(
        "SELECT Id FROM Supplier WHERE LOWER(Name) = LOWER(?) LIMIT 1",
        (supplier_name.strip(),),
    ).fetchone()
    return row[0] if row else None


def _component_belongs_to_product(connection: sqlite3.Connection, product_id: int, component_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM BOM b
        JOIN BOM_Component bc ON bc.BOMId = b.Id
        WHERE b.ProducedProductId = ?
        AND bc.ConsumedProductId = ?
        LIMIT 1
        """,
        (product_id, component_id),
    ).fetchone()
    return row is not None


def _supplier_supplies_product(connection: sqlite3.Connection, supplier_id: int, product_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM Supplier_Product
        WHERE SupplierId = ?
        AND ProductId = ?
        LIMIT 1
        """,
        (supplier_id, product_id),
    ).fetchone()
    return row is not None
