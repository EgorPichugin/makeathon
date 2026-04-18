from pydantic import BaseModel, Field


class RouteVectorRequest(BaseModel):
    component_name: str = Field(..., min_length=1)
    product_name: str | None = None
    supplier_name: str | None = None


class RouteVectorResponse(BaseModel):
    route_vector: list[int]
    product_structure: str | None
