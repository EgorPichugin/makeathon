"""Top-level orchestrator: LLM scorer per candidate (parallel) + deterministic ranker."""
from __future__ import annotations

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from google import genai

from services.spec_filler.product_spec import FilledProductMatrix

from . import db
from .models import RankingResult, ScoredCandidate
from .ranker import build_ranking
from .scorer import score_candidate

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
MAX_PARALLEL_CANDIDATES = 2

# USD per 1M tokens — same pricing table as spec_filler. Update if Google changes rates.
PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Put it in .env or set USE_VERTEX_AI=true with "
            "GOOGLE_CLOUD_PROJECT for Vertex AI + ADC auth."
        )
    return key


def _use_vertex() -> bool:
    return os.getenv("USE_VERTEX_AI", "").lower() in ("1", "true", "yes")


def _make_client() -> genai.Client:
    if _use_vertex():
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError("USE_VERTEX_AI=true requires GOOGLE_CLOUD_PROJECT.")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        logger.info("Using Vertex AI backend (project=%s, location=%s)", project, location)
        return genai.Client(vertexai=True, project=project, location=location)
    logger.info("Using AI Studio backend (API key)")
    return genai.Client(api_key=_api_key())


def _cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    rates = PRICING.get(MODEL)
    if not rates:
        return None
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def rank_suppliers(
    matrix: FilledProductMatrix,
    weights: dict[str, float] | None = None,
    critical_keywords: set[str] | None = None,
) -> RankingResult:
    """Rank suppliers in `matrix.companies[1:]` against `matrix.companies[0]` as the reference.

    Pipeline:
      1. Validate: need ≥2 companies, reference must have ≥1 found characteristic.
      2. LLM scorer (one Gemini call per candidate, run in parallel).
      3. build_ranking() — pure math: coverage × fit, hard filter on critical mismatches, sort.
      4. Optionally persist to Postgres if DATABASE_URL is set.
    """
    if len(matrix.companies) < 2:
        raise ValueError("Need at least 2 companies (companies[0] is the reference).")

    ref = matrix.companies[0]
    candidates = matrix.companies[1:]
    ref_found = [c for c in ref.characteristics if c.status == "found"]
    if not ref_found:
        raise ValueError(f"Reference '{ref.company}' has no found characteristics.")

    logger.info(
        "Ranking %d candidates vs reference '%s' (ref has %d/%d characteristics filled)",
        len(candidates), ref.company, len(ref_found), len(ref.characteristics),
    )

    client = _make_client()

    # Parallel LLM scoring per candidate.
    workers = min(MAX_PARALLEL_CANDIDATES, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(
                lambda cand: score_candidate(client, matrix.raw_material_name, ref, cand),
                candidates,
            )
        )

    scored: list[ScoredCandidate] = [r[0] for r in results]
    total_in = sum(r[1] for r in results)
    total_out = sum(r[2] for r in results)
    cost = _cost_usd(total_in, total_out)

    logger.info(
        "Scorer total: tokens in=%d out=%d | cost=%s",
        total_in, total_out,
        f"${cost:.6f}" if cost is not None else "n/a",
    )

    ranking = build_ranking(matrix, scored, weights, critical_keywords)
    ranking.rank_uuid = str(uuid.uuid4())
    ranking.tokens_in = total_in
    ranking.tokens_out = total_out
    ranking.cost_usd = cost

    for r in ranking.rankings:
        logger.info(
            "  #%d %s — overall=%.3f  coverage=%.2f  fit=%.2f  [%s]",
            r.rank, r.company, r.overall_score, r.coverage, r.fit_score, r.verdict,
        )
    for e in ranking.excluded:
        logger.info("  EXCLUDED %s — %s (%s)", e.company, e.verdict, e.reason)

    # Best-effort DB logging.
    if db.db_enabled():
        try:
            db.save_ranking(ranking)
        except Exception as e:
            logger.warning("Ranking DB save failed (non-fatal): %s", e)

    return ranking
