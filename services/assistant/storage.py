import json
import sqlite3
from pathlib import Path

from services.assistant.state import AppState, Intent


DEFAULT_DB_PATH = Path("data") / "assistant.db"


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
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


def load_thread_state(thread_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> AppState:
    path = Path(db_path)
    if not path.exists():
        return {}

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT intent, component_name, product_name, supplier_name, missing_fields, final_answer
            FROM assistant_threads
            WHERE thread_id = ?
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


def save_thread_state(thread_id: str, state: AppState, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
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
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(thread_id) DO UPDATE SET
                intent = excluded.intent,
                component_name = excluded.component_name,
                product_name = excluded.product_name,
                supplier_name = excluded.supplier_name,
                missing_fields = excluded.missing_fields,
                final_answer = excluded.final_answer,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                thread_id,
                _serialize_intent(state.get("intent")),
                state.get("component_name"),
                state.get("product_name"),
                state.get("supplier_name"),
                json.dumps(state.get("missing_fields", [])),
                state.get("final_answer"),
            ),
        )
        connection.commit()
def _serialize_intent(intent: Intent | str | None) -> str | None:
    if isinstance(intent, Intent):
        return intent.value
    return intent
