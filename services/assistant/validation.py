from services.db import get_connection


def validate_change_request_data(
    product_name: str,
    component_name: str,
    supplier_name: str,
) -> dict:
    validation_errors: list[str] = []
    invalid_fields: list[str] = []

    with get_connection() as connection:
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


def _get_product_id_by_sku(connection, sku: str) -> int | None:
    row = connection.execute(
        "SELECT Id FROM Product WHERE LOWER(SKU) = LOWER(%s) LIMIT 1",
        (sku.strip(),),
    ).fetchone()
    return row[0] if row else None


def _get_supplier_id_by_name(connection, supplier_name: str) -> int | None:
    row = connection.execute(
        "SELECT Id FROM Supplier WHERE LOWER(Name) = LOWER(%s) LIMIT 1",
        (supplier_name.strip(),),
    ).fetchone()
    return row[0] if row else None


def _component_belongs_to_product(connection, product_id: int, component_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM BOM b
        JOIN BOM_Component bc ON bc.BOMId = b.Id
        WHERE b.ProducedProductId = %s
        AND bc.ConsumedProductId = %s
        LIMIT 1
        """,
        (product_id, component_id),
    ).fetchone()
    return row is not None


def _supplier_supplies_product(connection, supplier_id: int, product_id: int) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM Supplier_Product
        WHERE SupplierId = %s
        AND ProductId = %s
        LIMIT 1
        """,
        (supplier_id, product_id),
    ).fetchone()
    return row is not None
