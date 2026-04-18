from typing import Literal
from pydantic import BaseModel, create_model # type: ignore


class Default(BaseModel):
    certificate: str | None = None


class Dimensions(BaseModel):
    length: float | None = None
    width: float | None = None
    height: float | None = None
    unit: Literal["mm", "cm", "m", "in"] | None = None


class Volume(BaseModel):
    volume: float | None = None
    unit: Literal["ml", "l", "oz"] | None = None


IngredientMetadata = create_model(
    "IngredientMetadata",
    physical_form = (Literal["powder", "liquid", "solid", "extract"], ...),
    __base__=Default)

ConsumableIngredientMetadata = create_model(
    "ConsumableIngredientMetadata",
    functional_role= (Literal[
        "active", "nutrient", "flavor", "colorant",
        "sweetener", "preservative", "excipient"
        ], ...),
    __base__=IngredientMetadata
)

NonConsumableIngredientMetadata = create_model(
    "NonConsumableIngredientMetadata",
    material_type = (Literal["plastic", "glass", "paper", "foil", "metal", "composite"], ...),
    __base__=IngredientMetadata
)

DimensionalNonConsumableIngredientMetadata = create_model(
    "DimensionalNonConsumableIngredientMetadata",
    dimension = Dimensions | None,
    __base__=IngredientMetadata
)


PackagingMetadata = create_model(
    "PackagingMetadata",
    package_type = (Literal[
        "bottle", "lid", "cap", "pouch", "label",
        "box", "blister", "sachet", "scoop"
        ], ...),
    material_type = (Literal["plastic", "glass", "paper", "foil", "metal", "composite"], ...),
    __base__=Default
)

DimensionalPackagingMetadata = create_model(
    "DimensionalPackagingMetadata",
    dimension = Dimensions | None,
    volume = Volume | None,
    __base__=PackagingMetadata
)

NonDimensionalPackagingMetadata = create_model(
    "NonDimensionalPackagingMetadata",
    __base__=PackagingMetadata
)
