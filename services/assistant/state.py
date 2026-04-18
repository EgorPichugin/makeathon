from enum import Enum
from typing import TypedDict


class Intent(Enum):
    SIDE_QUESTION = "side_question"
    CHANGE_COMPONENT = "change_component"


class AppState(TypedDict, total=False):
    user_message: str
    intent: Intent
    component_name: str | None
    product_name: str | None
    supplier_name: str | None
    route_vector: list[int] | None
    missing_fields: list[str]
    validation_errors: list[str]
    final_answer: str
