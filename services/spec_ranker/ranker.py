"""Pure math: turns per-candidate CellScores into a final ranking."""
from __future__ import annotations

import logging
import re

from services.spec_filler.product_spec import FilledProductMatrix

from .models import (
    ExcludedSupplier,
    RankingResult,
    ReferenceInfo,
    ScoredCandidate,
    SupplierRanking,
)

logger = logging.getLogger(__name__)

_DEFAULT_CRITICAL_REGEX = re.compile(r"\bcas\b", re.IGNORECASE)


def _is_critical(name: str, critical_keywords: set[str] | None) -> bool:
    """Is this characteristic a hard-filter (mismatch → excluded)?

    Default: any characteristic whose name contains "CAS".
    Override by passing `critical_keywords`.
    """
    if critical_keywords:
        n = name.lower()
        return any(kw.lower() in n for kw in critical_keywords)
    return bool(_DEFAULT_CRITICAL_REGEX.search(name))


def _verdict_for(overall: float) -> str:
    if overall >= 0.75:
        return "Equivalent"
    if overall >= 0.5:
        return "Likely substitute"
    if overall >= 0.25:
        return "Partial match"
    return "Poor match"


def build_ranking(
    matrix: FilledProductMatrix,
    scored_candidates: list[ScoredCandidate],
    weights: dict[str, float] | None = None,
    critical_keywords: set[str] | None = None,
) -> RankingResult:
    """Combine scorer output into final ranking.

    Formula (per candidate):
      coverage = |candidate-found among ref-found| / |ref-found|
      fit      = Σ match·trust·w  /  Σ w   (only over chars where candidate has data)
      overall  = coverage · fit

    Hard filter: if ANY critical characteristic (default: "CAS") has match=0 with a
    non-null candidate_value, the supplier is excluded with verdict "Different substance".
    """
    if len(matrix.companies) < 2:
        raise ValueError("Need at least 2 companies: companies[0] is the reference.")

    ref = matrix.companies[0]
    ref_found = [c for c in ref.characteristics if c.status == "found"]
    if not ref_found:
        raise ValueError(
            f"Reference '{ref.company}' has no found characteristics — cannot rank."
        )

    weights = weights or {}

    rankings: list[SupplierRanking] = []
    excluded: list[ExcludedSupplier] = []

    for scored in scored_candidates:
        cells = scored.cells

        # ---- Hard filter: critical mismatch
        critical_mismatches = [
            c for c in cells
            if _is_critical(c.characteristic, critical_keywords)
            and c.candidate_value is not None  # only if candidate actually had a value
            and c.match == 0
        ]
        if critical_mismatches:
            excluded.append(ExcludedSupplier(
                company=scored.company,
                verdict="Different substance",
                reason=(
                    "Critical mismatch on: "
                    + ", ".join(c.characteristic for c in critical_mismatches)
                ),
                cells=cells,
            ))
            continue

        # ---- Coverage: fraction of reference's known characteristics the candidate also knows
        candidate_has_data = [c for c in cells if c.candidate_value is not None]
        coverage = len(candidate_has_data) / len(ref_found) if ref_found else 0.0

        # ---- Fit: weighted average of match*trust over candidate's covered cells
        if candidate_has_data:
            w_sum = sum(weights.get(c.characteristic, 1.0) for c in candidate_has_data)
            fit_sum = sum(
                c.match * c.trust * weights.get(c.characteristic, 1.0)
                for c in candidate_has_data
            )
            fit_score = fit_sum / w_sum if w_sum > 0 else 0.0
        else:
            fit_score = 0.0

        overall = coverage * fit_score

        # ---- Insufficient data → exclude (not ranked)
        if coverage == 0.0:
            excluded.append(ExcludedSupplier(
                company=scored.company,
                verdict="Insufficient data",
                reason="Candidate has no data for any characteristic the reference covers",
                cells=cells,
            ))
            continue

        rankings.append(SupplierRanking(
            rank=0,  # assigned after sort
            company=scored.company,
            coverage=round(coverage, 4),
            fit_score=round(fit_score, 4),
            overall_score=round(overall, 4),
            verdict=_verdict_for(overall),
            cells=cells,
        ))

    # ---- Sort + assign rank
    rankings.sort(key=lambda r: r.overall_score, reverse=True)
    for i, r in enumerate(rankings, 1):
        r.rank = i

    reference = ReferenceInfo(
        company=ref.company,
        total_characteristics=len(ref.characteristics),
        found_characteristics=len(ref_found),
        coverage=round(len(ref_found) / len(ref.characteristics), 4) if ref.characteristics else 0.0,
    )

    return RankingResult(
        raw_material_name=matrix.raw_material_name,
        reference=reference,
        rankings=rankings,
        excluded=excluded,
        run_uuid=matrix.run_uuid,
    )
