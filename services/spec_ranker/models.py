from typing import Literal

from pydantic import BaseModel, Field


class CellScore(BaseModel):
    characteristic: str
    reference_value: str | None
    reference_source: str | None
    candidate_value: str | None
    candidate_source: str | None
    trust: int = Field(..., ge=0, le=1, description="1 if candidate_source is trusted for this candidate, 0 otherwise")
    match: int = Field(..., ge=0, le=1, description="1 if candidate value is equivalent to reference value, 0 otherwise")
    rationale: str


class ScoredCandidate(BaseModel):
    """LLM scorer output (one candidate vs the reference)."""
    company: str
    cells: list[CellScore]


class SupplierRanking(BaseModel):
    rank: int
    company: str
    coverage: float = Field(..., description="Fraction of reference's found characteristics that the candidate also covers")
    fit_score: float = Field(..., description="Weighted average of match*trust over characteristics the candidate covered")
    overall_score: float = Field(..., description="coverage * fit_score")
    verdict: Literal["Equivalent", "Likely substitute", "Partial match", "Poor match"]
    cells: list[CellScore]


class ExcludedSupplier(BaseModel):
    company: str
    verdict: Literal["Different substance", "Insufficient data"]
    reason: str
    cells: list[CellScore]


class ReferenceInfo(BaseModel):
    company: str
    total_characteristics: int
    found_characteristics: int
    coverage: float = Field(..., description="Fraction of characteristics the reference itself has filled")


class RankingResult(BaseModel):
    raw_material_name: str
    reference: ReferenceInfo
    rankings: list[SupplierRanking]
    excluded: list[ExcludedSupplier]
    run_uuid: str | None = Field(default=None, description="FK to spec_filler result_tables.run_uuid, if provided")
    rank_uuid: str | None = Field(default=None, description="UUID of this ranking run")
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None