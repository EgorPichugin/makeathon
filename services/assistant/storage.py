import json

from services.assistant.state import AppState, Intent
from services.db import get_connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assistant_threads (
                thread_id TEXT PRIMARY KEY,
                intent TEXT,
                component_name TEXT,
                product_name TEXT,
                supplier_name TEXT,
                missing_fields TEXT NOT NULL DEFAULT '[]',
                final_answer TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def load_thread_state(thread_id: str) -> AppState:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT intent, component_name, product_name, supplier_name, missing_fields, final_answer
            FROM assistant_threads
            WHERE thread_id = %s
            """,
            (thread_id,),
        ).fetchone()

    if row is None:
        return {}

    intent = row[0]
    return {
        "intent": Intent(intent) if intent else None,
        "component_name": row[1],
        "product_name": row[2],
        "supplier_name": row[3],
        "missing_fields": json.loads(row[4]) if row[4] else [],
        "final_answer": row[5],
    }


def save_thread_state(thread_id: str, state: AppState) -> None:
    state_to_save = _state_for_persistence(state)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO assistant_threads (
                thread_id,
                intent,
                component_name,
                product_name,
                supplier_name,
                missing_fields,
                final_answer,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(thread_id) DO UPDATE SET
                intent = EXCLUDED.intent,
                component_name = EXCLUDED.component_name,
                product_name = EXCLUDED.product_name,
                supplier_name = EXCLUDED.supplier_name,
                missing_fields = EXCLUDED.missing_fields,
                final_answer = EXCLUDED.final_answer,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                thread_id,
                _serialize_intent(state_to_save.get("intent")),
                state_to_save.get("component_name"),
                state_to_save.get("product_name"),
                state_to_save.get("supplier_name"),
                json.dumps(state_to_save.get("missing_fields", [])),
                state_to_save.get("final_answer"),
            ),
        )
        connection.commit()


def _state_for_persistence(state: AppState) -> AppState:
    if _is_completed_change_request(state):
        return {
            "intent": state.get("intent"),
            "missing_fields": [],
            "final_answer": state.get("final_answer"),
        }
    return state


def _is_completed_change_request(state: AppState) -> bool:
    return (
        _serialize_intent(state.get("intent")) == "change_component"
        and not state.get("missing_fields")
        and not state.get("validation_errors")
        and bool(state.get("final_answer"))
    )


def _serialize_intent(intent: Intent | str | None) -> str | None:
    if isinstance(intent, Intent):
        return intent.value
    return intent
