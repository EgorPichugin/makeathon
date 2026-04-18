from fastapi import APIRouter
from pydantic import BaseModel
from services.assistant.functions import (
    get_product_suppliers,
    get_supplier_components_for_product,
)
from services.assistant.validation import validate_change_request_data
from services.db import get_connection


router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("", response_model=list[str])
def list_companies() -> list[str]:
    with get_connection() as connection:
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


class ProductListResponse(BaseModel):
    supplier_id: int
    products: list[str]


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
    )
    return ValidationResponse(
        is_valid=not result["validation_errors"],
        validation_errors=result["validation_errors"],
    )


@router.get("/product/{product_id}/suppliers", response_model=SupplierListResponse)
def list_product_suppliers(product_id: int) -> SupplierListResponse:
    return SupplierListResponse(
        product_id=product_id,
        suppliers=get_product_suppliers(product_id),
    )


@router.get("/supplier/{supplier_id}/products", response_model=ProductListResponse)
def list_supplier_products(supplier_id: int) -> ProductListResponse:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT p.SKU
            FROM Supplier_Product sp
            JOIN Product p ON p.Id = sp.ProductId
            WHERE sp.SupplierId = %s
            AND p.SKU IS NOT NULL
            AND TRIM(p.SKU) != ''
            ORDER BY p.SKU
            """,
            (supplier_id,),
        ).fetchall()

    return ProductListResponse(
        supplier_id=supplier_id,
        products=[row[0] for row in rows],
    )


@router.get("/product/{product_name}/supplier-components", response_model=dict[str, list[str]])
def list_supplier_components_for_product(product_name: str) -> dict[str, list[str]]:
    return get_supplier_components_for_product(product_name)
