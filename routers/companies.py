import sqlite3
from pathlib import Path

from core.config import CPG_DB_PATH
from fastapi import APIRouter
from pydantic import BaseModel
from services.assistant.validation import validate_change_request_data


router = APIRouter(prefix="/companies", tags=["companies"])

CPG_DB_FILE = Path(CPG_DB_PATH)

@router.get("", response_model=list[str])
def list_companies() -> list[str]:
    with sqlite3.connect(CPG_DB_FILE) as connection:
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

    result = validate_change_request_data(
        product_name=payload.product_name,
        component_name=payload.component_name,
        supplier_name=payload.supplier_name,
        db_path=CPG_DB_FILE,
    )
    return ValidationResponse(
        is_valid=not result["validation_errors"],
        validation_errors=result["validation_errors"],
    )


@router.get("/product/{product_id}/suppliers", response_model=SupplierListResponse)
def list_product_suppliers(product_id: int) -> SupplierListResponse:
    with sqlite3.connect(CPG_DB_FILE) as connection:
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
