from typing import Literal

from pydantic import BaseModel, Field


class ProductQuery(BaseModel):
    raw_material_name: str = Field(..., description="Generic raw material / product category name, e.g. '16-inch professional laptop'")
    characteristics: list[str] = Field(..., description="Ordered list of characteristic names to fill")
    companies: list[str] = Field(..., description="Companies/brands to look up this raw material for")


class FilledCharacteristic(BaseModel):
    name: str
    value: str | None
    source_url: str | None
    status: Literal["found", "not_found"]


class CompanyProductSpec(BaseModel):
    company: str
    characteristics: list[FilledCharacteristic]


class FilledProductMatrix(BaseModel):
    raw_material_name: str
    companies: list[CompanyProductSpec]
    run_uuid: str | None = Field(
        default=None,
        description="UUID of the DB run row (result_tables.run_uuid). None if DB logging was disabled or failed.",
    )
    table_name: str | None = Field(
        default=None,
        description="Name of the dynamic per-run Postgres table with JSONB cells. None if DB logging was disabled or failed.",
    )