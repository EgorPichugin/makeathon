"""LLM scoring: one Gemini call per candidate → per-cell {trust, match, rationale}."""
from __future__ import annotations

import json
import logging

from google import genai
from google.genai import types
from pydantic import ValidationError

from services.spec_filler.product_spec import CompanyProductSpec

from .models import ScoredCandidate

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

SCORE_PROMPT = """You compare a CANDIDATE supplier's raw material offering against a REFERENCE supplier to decide if the candidate's product is an EQUIVALENT REPLACEMENT.

Raw material: {raw_material}
Reference company: {reference_company}
Candidate company: {candidate_company}

For each characteristic below, decide two BINARY values:

1. TRUST (for the candidate's source_url):
   - 1 if the candidate's source_url is a credible source FOR THIS SPECIFIC CANDIDATE:
     * the candidate's own corporate domain, OR
     * a distributor / B2B directory page that explicitly names the candidate as the supplier of this product variant.
   - 0 otherwise — including Wikipedia, PubChem, NIH, USP monograph, FDA GRAS, Mayo Clinic, Healthline, generic chemistry databases, or any page that describes the chemical in general without naming the candidate as the supplier.

2. MATCH (candidate value vs reference value):
   - 1 if the candidate's value is EQUIVALENT to the reference's value — exact equality OR clear semantic equivalence (e.g., "powder" ≡ "fine powder", "1%" ≡ "1.0%", "7235-40-7" ≡ "7235-40-7").
   - 0 if different (e.g., "1%" vs "10%", "powder" vs "beadlet", "water-soluble" vs "oil-soluble", different CAS numbers).

Special rules:
- If candidate_value is null (candidate has no data): match=0, trust=0, rationale="candidate has no data for this characteristic".
- CAS number differences mean fundamentally different substances → match=0.
- If the candidate_source_url belongs to a different company than the candidate (e.g., a reference manufacturer's page), trust=0.

Provide a SHORT rationale (1 sentence) per cell.

=== Characteristics (in this order) ===
{pairs}

Return a ScoredCandidate JSON: company="{candidate_company}" and cells[] with one entry per characteristic above, in the same order.
"""


def _build_pairs_block(
    ref: CompanyProductSpec, candidate: CompanyProductSpec
) -> tuple[str, list[dict]]:
    """Return a human-readable block + a list of (characteristic, ref, cand) triples for reference.

    Only includes characteristics where the reference has a found value (candidates can be missing).
    """
    cand_by_name = {c.name: c for c in candidate.characteristics}
    rows: list[dict] = []
    lines: list[str] = []
    for idx, ref_char in enumerate(ref.characteristics, 1):
        if ref_char.status != "found":
            continue
        cand_char = cand_by_name.get(ref_char.name)
        cand_val = cand_char.value if cand_char and cand_char.status == "found" else None
        cand_src = cand_char.source_url if cand_char and cand_char.status == "found" else None
        rows.append({
            "characteristic": ref_char.name,
            "reference_value": ref_char.value,
            "reference_source": ref_char.source_url,
            "candidate_value": cand_val,
            "candidate_source": cand_src,
        })
        lines.append(
            f"[{idx}] {ref_char.name}\n"
            f"    reference: value={ref_char.value!r}  source={ref_char.source_url!r}\n"
            f"    candidate: value={cand_val!r}  source={cand_src!r}"
        )
    return "\n\n".join(lines), rows


def score_candidate(
    client: genai.Client,
    raw_material: str,
    reference: CompanyProductSpec,
    candidate: CompanyProductSpec,
) -> tuple[ScoredCandidate, int, int]:
    """Run the LLM scorer for one candidate. Returns (scored, input_tokens, output_tokens)."""
    pairs_block, _rows = _build_pairs_block(reference, candidate)
    if not pairs_block:
        logger.warning("[rank %s] no comparable characteristics (reference has no found cells)",
                       candidate.company)
        return ScoredCandidate(company=candidate.company, cells=[]), 0, 0

    response = client.models.generate_content(
        model=MODEL,
        contents=SCORE_PROMPT.format(
            raw_material=raw_material,
            reference_company=reference.company,
            candidate_company=candidate.company,
            pairs=pairs_block,
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ScoredCandidate,
            temperature=0.0,
        ),
    )

    raw = response.text or ""
    try:
        scored = ScoredCandidate.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("[rank %s] scorer parse failed (%s), retrying via json.loads",
                       candidate.company, e)
        scored = ScoredCandidate.model_validate(json.loads(raw))

    in_t = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
    out_t = (getattr(response.usage_metadata, "candidates_token_count", 0) or 0) + (
        getattr(response.usage_metadata, "thoughts_token_count", 0) or 0
    )
    return scored, in_t, out_t