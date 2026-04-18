import sqlite3
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/companies", tags=["companies"])

CPG_DB_PATH = Path(r"C:\Users\pichu\Documents\repos\hackaton\db.sqlite")


@router.get("", response_model=list[str])
def list_companies() -> list[str]:
    with sqlite3.connect(CPG_DB_PATH) as connection:
        rows = connection.execute(
            """
            SELECT Name
            FROM Company
            WHERE Name IS NOT NULL AND TRIM(Name) != ''
            ORDER BY Name
            """
        ).fetchall()
    return [row[0] for row in rows]


class ValidationRequest(BaseModel):
    product_name: str
    component_name: str
    supplier_name: str


class ValidationResponse(BaseModel):
    is_valid: bool
    validation_errors: list[str]


class SupplierListResponse(BaseModel):
    product_id: int
    suppliers: list[str]


@router.post("/validate", response_model=ValidationResponse)
def validate_request(payload: ValidationRequest) -> ValidationResponse:
    validation_errors: list[str] = []

    if not payload.product_name.strip():
        validation_errors.append("Product name is required.")
    if not payload.component_name.strip():
        validation_errors.append("Component name is required.")
    if not payload.supplier_name.strip():
        validation_errors.append("Supplier name is required.")

    if validation_errors:
        return ValidationResponse(is_valid=False, validation_errors=validation_errors)

    with sqlite3.connect(CPG_DB_PATH) as connection:
        product_id = _get_product_id_by_sku(connection, payload.product_name)
        component_id = _get_product_id_by_sku(connection, payload.component_name)
        supplier_id = _get_supplier_id_by_name(connection, payload.supplier_name)

        if product_id is None:
            validation_errors.append(
                f"Product '{payload.product_name}' was not found in Product.SKU."
            )
        if component_id is None:
            validation_errors.append(
                f"Component '{payload.component_name}' was not found in Product.SKU."
            )
        if supplier_id is None:
            validation_errors.append(
                f"Supplier '{payload.supplier_name}' was not found in Supplier.Name."
            )
        if not validation_errors:
            if not _component_belongs_to_product(connection, product_id, component_id):
                validation_errors.append(
                    f"Component '{payload.component_name}' is not a BOM component of product '{payload.product_name}'."
                )
            if not _supplier_supplies_product(connection, supplier_id, component_id):
                validation_errors.append(
                    f"Supplier '{payload.supplier_name}' does not supply raw material '{payload.component_name}'."
                )
            if _supplier_supplies_product(connection, supplier_id, product_id):
                validation_errors.append(
                    f"Supplier '{payload.supplier_name}' already supplies finished good '{payload.product_name}', which is not allowed by this rule."
                )

    return ValidationResponse(is_valid=not validation_errors, validation_errors=validation_errors)


@router.get("/product/{product_id}/suppliers", response_model=SupplierListResponse)
def list_product_suppliers(product_id: int) -> SupplierListResponse:
    with sqlite3.connect(CPG_DB_PATH) as connection:
        rows = connection.execute(
            """
            SELECT s.Name
            FROM Supplier_Product sp
            JOIN Supplier s ON s.Id = sp.SupplierId
            WHERE sp.ProductId = ?
            AND s.Name IS NOT NULL
            AND TRIM(s.Name) != ''
            ORDER BY s.Name
            """,
            (product_id,),
        ).fetchall()

    return SupplierListResponse(
        product_id=product_id,
        suppliers=[row[0] for row in rows],
    )


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
