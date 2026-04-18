import sqlite3
from pathlib import Path
from core.config import ASSISTANT_DB_PATH


def validate_change_request_data(
    product_name: str,
    component_name: str,
    supplier_name: str,
    db_path: str | Path = ASSISTANT_DB_PATH,
) -> dict:
    validation_errors: list[str] = []
    invalid_fields: list[str] = []

    with sqlite3.connect(db_path) as connection:
        product_id = _get_product_id_by_sku(connection, product_name)
        component_id = _get_product_id_by_sku(connection, component_name)
        supplier_id = _get_supplier_id_by_name(connection, supplier_name)

        if product_id is None:
            invalid_fields.append("product_name")
            validation_errors.append(
                f"Product '{product_name}' was not found in Product.SKU."
            )
        if component_id is None:
            invalid_fields.append("component_name")
            validation_errors.append(
                f"Component '{component_name}' was not found in Product.SKU."
            )
        if supplier_id is None:
            invalid_fields.append("supplier_name")
            validation_errors.append(
                f"Supplier '{supplier_name}' was not found in Supplier.Name."
            )
        if validation_errors:
            return {
                "validation_errors": validation_errors,
                "invalid_fields": list(dict.fromkeys(invalid_fields)),
            }

        if not _component_belongs_to_product(connection, product_id, component_id):
            invalid_fields.append("component_name")
            validation_errors.append(
                f"Component '{component_name}' is not a BOM component of product '{product_name}'."
            )
        if not _supplier_supplies_product(connection, supplier_id, component_id):
            invalid_fields.append("supplier_name")
            validation_errors.append(
                f"Supplier '{supplier_name}' does not supply raw material '{component_name}'."
            )
        if _supplier_supplies_product(connection, supplier_id, product_id):
            invalid_fields.append("supplier_name")
            validation_errors.append(
                f"Supplier '{supplier_name}' already supplies finished good '{product_name}', which is not allowed by this rule."
            )

    return {
        "validation_errors": validation_errors,
        "invalid_fields": list(dict.fromkeys(invalid_fields)),
    }


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
