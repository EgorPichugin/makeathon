from services.assistant.llm import get_structured_llm
from services.assistant.models import (
    ChangeComponentUpdateResult,
    ConversationIntentResult,
    NavigationComponentTreeResult,
)
from services.assistant.observability import invoke_with_logging
from services.assistant.prompts import (
    CHANGE_COMPONENT_UPDATE_PROMPT,
    INTENT_ROUTER_PROMPT,
    NAVIGATE_COMPONENT_TREE_REQUEST,
)
from services.assistant.state import AppState, Intent
from services.assistant.validation import validate_change_request_data
from services.db import get_connection

from schemas.component import (
    ConsumableIngredientMetadata,
    DimensionalNonConsumableIngredientMetadata,
    DimensionalPackagingMetadata,
    NonConsumableIngredientMetadata,
    NonDimensionalPackagingMetadata,
)


def detect_intent(state: AppState) -> Intent:
    prompt = INTENT_ROUTER_PROMPT.format(
        component_name=state.get("component_name"),
        product_name=state.get("product_name"),
        supplier_name=state.get("supplier_name"),
        missing_fields=state.get("missing_fields", []),
        user_message=state["user_message"],
    )
    result: ConversationIntentResult = invoke_with_logging(
        "detect_intent_llm",
        get_structured_llm(ConversationIntentResult),
        prompt,
    )
    return result.intent


def extract_change_component_update(state: AppState) -> dict:
    prompt = CHANGE_COMPONENT_UPDATE_PROMPT.format(
        component_name=state.get("component_name"),
        product_name=state.get("product_name"),
        supplier_name=state.get("supplier_name"),
        missing_fields=state.get("missing_fields", []),
        user_message=state["user_message"],
    )
    result: ChangeComponentUpdateResult = invoke_with_logging(
        "extract_change_component_update_llm",
        get_structured_llm(ChangeComponentUpdateResult),
        prompt,
    )
    extracted_data = result.model_dump()

    updated_state = {
        "component_name": normalize_optional_text(
            extracted_data["component_name"],
            state.get("component_name"),
        ),
        "product_name": normalize_optional_text(
            extracted_data["product_name"],
            state.get("product_name"),
        ),
        "supplier_name": normalize_optional_text(
            extracted_data["supplier_name"],
            state.get("supplier_name"),
        ),
    }
    updated_state["missing_fields"] = find_missing_fields(updated_state)
    return updated_state


def normalize_optional_text(new_value: str | None, current_value: str | None) -> str | None:
    if new_value is None:
        return current_value
    normalized = new_value.strip()
    return normalized or current_value


def find_missing_fields(data: dict) -> list[str]:
    missing_fields: list[str] = []
    if not data.get("component_name"):
        missing_fields.append("component_name")
    if not data.get("product_name"):
        missing_fields.append("product_name")
    if not data.get("supplier_name"):
        missing_fields.append("supplier_name")
    return missing_fields


def validate_change_request(state: AppState) -> dict:
    return validate_change_request_data(
        product_name=state["product_name"],
        component_name=state["component_name"],
        supplier_name=state["supplier_name"],
    )


def get_product_suppliers(product_id: int) -> list[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT s.Name
            FROM Supplier_Product sp
            JOIN Supplier s ON s.Id = sp.SupplierId
            WHERE sp.ProductId = %s
            AND s.Name IS NOT NULL
            AND TRIM(s.Name) != ''
            ORDER BY s.Name
            """,
            (product_id,),
        ).fetchall()
    return [row[0] for row in rows]


def get_supplier_components_for_product(product_name: str) -> dict[str, list[str]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT s.Name, component.SKU
            FROM Product finished_product
            JOIN BOM b ON b.ProducedProductId = finished_product.Id
            JOIN BOM_Component bc ON bc.BOMId = b.Id
            JOIN Product component ON component.Id = bc.ConsumedProductId
            JOIN Supplier_Product sp ON sp.ProductId = bc.ConsumedProductId
            JOIN Supplier s ON s.Id = sp.SupplierId
            WHERE LOWER(finished_product.SKU) = LOWER(%s)
            AND s.Name IS NOT NULL
            AND TRIM(s.Name) != ''
            AND component.SKU IS NOT NULL
            AND TRIM(component.SKU) != ''
            ORDER BY s.Name, component.SKU
            """,
            (product_name.strip(),),
        ).fetchall()

    supplier_components: dict[str, list[str]] = {}
    for supplier_name, component_sku in rows:
        if supplier_name not in supplier_components:
            supplier_components[supplier_name] = []
        if component_sku not in supplier_components[supplier_name]:
            supplier_components[supplier_name].append(component_sku)

    return supplier_components

def get_route_vector(state: AppState) -> list[int]:
    component_structure_prompt = NAVIGATE_COMPONENT_TREE_REQUEST.format(
        product_name=state.get("product_name", ""),
        component_name=state.get("component_name", ""),
        supplier_name=state.get("supplier_name", ""),
    )

    result: NavigationComponentTreeResult = invoke_with_logging(
        "navigate_component_tree_llm",
        get_structured_llm(NavigationComponentTreeResult),
        component_structure_prompt,
    )

    return result.route_vector

def get_route_vector_for_product(supplier_name: str, component_name: str) -> list[int]:
    component_structure_prompt = NAVIGATE_COMPONENT_TREE_REQUEST.format(
        product_name="",
        component_name=component_name,
        supplier_name=supplier_name,
    )

    result: NavigationComponentTreeResult = invoke_with_logging(
        "navigate_component_tree_llm",
        get_structured_llm(NavigationComponentTreeResult),
        component_structure_prompt,
    )
    return result.route_vector

def get_product_structure(route_vector: list[int]) -> dict | None:
    if route_vector == [0, 0, 0]:
        return ConsumableIngredientMetadata().model_dump()
    elif route_vector == [0, 1, 0]:
        return NonConsumableIngredientMetadata().model_dump()
    elif route_vector == [0, 1, 1]:
        return DimensionalNonConsumableIngredientMetadata().model_dump()
    elif route_vector == [1, 0, 0]:
        return NonDimensionalPackagingMetadata().model_dump()
    elif route_vector == [1, 1, 0]:
        return DimensionalPackagingMetadata().model_dump()
    return None

def get_filtered_products_by_route_vector(products: dict[str, list[str]], route_vector: list[int]) -> dict[str, list[str]]:
    filtered = {}
    for supplier, product_names in products.items():
        for product in product_names:
            product_vector = get_route_vector_for_product(supplier, product)
            if product_vector == route_vector:
                if supplier not in filtered:
                    filtered[supplier] = []
                filtered[supplier].append(product)
    return filtered


# ---------------------------------------------------------------------------
# spec_filler / spec_ranker integration helpers
# ---------------------------------------------------------------------------

from services.spec_filler import ProductQuery, find_product_info
from services.spec_ranker import rank_suppliers


def list_characteristics_for_route(route_vector: list[int]) -> list[str]:
    """Return the Pydantic field names of the metadata schema chosen by the route vector.

    These are the characteristics our spec_filler agent will try to fill from the web for
    each supplier. If the route vector doesn't match any known schema, returns an empty list.
    """
    structure = get_product_structure(route_vector)
    if structure is None:
        return []
    return list(structure.keys())


def build_candidate_company_list(
    current_supplier: str,
    filtered_suppliers: dict[str, list[str]],
) -> list[str]:
    """Order companies so that the CURRENT (to-be-replaced) supplier is first (reference),
    followed by candidate alternatives. Duplicates removed.
    """
    ordered: list[str] = [current_supplier]
    for supplier in filtered_suppliers:
        if supplier and supplier != current_supplier and supplier not in ordered:
            ordered.append(supplier)
    return ordered


def fill_component_specs(
    component_name: str,
    characteristics: list[str],
    companies: list[str],
) -> dict:
    """Run spec_filler to fill characteristics for each company. Returns the matrix as a plain dict
    so it can travel through LangGraph state (TypedDict) without custom serializers.
    """
    query = ProductQuery(
        raw_material_name=component_name,
        characteristics=characteristics,
        companies=companies,
    )
    matrix = find_product_info(query)
    return matrix.model_dump()


def rank_component_suppliers(matrix_dict: dict) -> dict:
    """Run spec_ranker on the filled matrix dict. Returns the ranking result as a plain dict."""
    # Import here to keep the module-level import surface small.
    from services.spec_filler.product_spec import FilledProductMatrix

    matrix = FilledProductMatrix.model_validate(matrix_dict)
    result = rank_suppliers(matrix)
    return result.model_dump()


def _reference_cells_from_ranking(ranking_dict: dict) -> list[dict]:
    """Pull the reference-side cell list from the first ranking/excluded entry.

    The ranker uses the same set of characteristics (those where the reference has data) for
    every candidate, so any entry's `cells` list gives us the reference picture.
    """
    for entry in ranking_dict.get("rankings", []) + ranking_dict.get("excluded", []):
        if entry.get("cells"):
            return entry["cells"]
    return []


def format_ranking_answer(ranking_dict: dict) -> str:
    """Render a ranking result as a readable markdown message for the chat UI."""
    raw_material = ranking_dict.get("raw_material_name", "(unknown)")
    ref = ranking_dict.get("reference", {}) or {}
    rankings = ranking_dict.get("rankings", []) or []
    excluded = ranking_dict.get("excluded", []) or []

    best_score = max((r.get("overall_score", 0.0) for r in rankings), default=0.0)
    # Classify outcome for the headline: user-facing language, no scores here.
    if best_score >= 0.5:
        headline = (
            f"## Found {sum(1 for r in rankings if r.get('overall_score', 0) >= 0.5)} "
            f"viable replacement(s) for `{raw_material}`"
        )
    elif best_score >= 0.25:
        headline = (
            f"## No strong replacement for `{raw_material}` — "
            f"{len(rankings)} partial match(es) found"
        )
    else:
        headline = f"## No suitable replacement found for `{raw_material}`"

    lines: list[str] = [headline, ""]

    # Current supplier summary
    lines.append(
        f"**Current supplier:** {ref.get('company', '?')} — "
        f"{ref.get('found_characteristics', 0)}/{ref.get('total_characteristics', 0)} "
        f"characteristics publicly documented"
    )
    ref_cells = _reference_cells_from_ranking(ranking_dict)
    if ref_cells:
        for c in ref_cells:
            val = c.get("reference_value") or "?"
            src = c.get("reference_source") or ""
            link = f" ([source]({src}))" if src else ""
            lines.append(f"- {c.get('characteristic', '?')}: `{val}`{link}")

    # Ranked alternatives (even Poor match: user asked to list all)
    if rankings:
        lines.append("")
        lines.append(f"### Alternatives ranked ({len(rankings)})")
        for r in rankings:
            cells = r.get("cells", []) or []
            matches = [c for c in cells if c.get("match") == 1 and c.get("trust") == 1]
            issues = [
                c for c in cells
                if c.get("candidate_value") is not None
                and (c.get("match") == 0 or c.get("trust") == 0)
            ]
            missing = [c for c in cells if c.get("candidate_value") is None]

            lines.append("")
            lines.append(
                f"**#{r.get('rank', '?')}. {r.get('company', '?')}** — "
                f"{r.get('verdict', '?')} "
                f"(score {r.get('overall_score', 0):.2f}, "
                f"coverage {r.get('coverage', 0):.0%}, "
                f"fit {r.get('fit_score', 0):.0%})"
            )
            if matches:
                lines.append("  **What matches:**")
                for c in matches:
                    why = c.get("rationale") or ""
                    val = c.get("candidate_value") or "?"
                    lines.append(
                        f"    - {c.get('characteristic', '?')}: `{val}`"
                        + (f" — {why}" if why else "")
                    )
            if issues:
                lines.append("  **Differences or low-trust sources:**")
                for c in issues:
                    why = c.get("rationale") or ""
                    ref_val = c.get("reference_value") or "?"
                    cand_val = c.get("candidate_value") or "?"
                    lines.append(
                        f"    - {c.get('characteristic', '?')}: candidate `{cand_val}` "
                        f"vs reference `{ref_val}`"
                        + (f" — {why}" if why else "")
                    )
            if missing:
                names = ", ".join(c.get("characteristic", "?") for c in missing)
                lines.append(f"  **Missing on their page:** {names}")

    # Excluded (hard filter or insufficient data)
    if excluded:
        lines.append("")
        lines.append(f"### Not suitable ({len(excluded)})")
        for e in excluded:
            lines.append(
                f"- **{e.get('company', '?')}** — {e.get('verdict', '?')}: "
                f"{e.get('reason', '')}"
            )

    if not rankings and not excluded:
        lines.append("")
        lines.append("_No candidate suppliers were evaluated._")

    cost = ranking_dict.get("cost_usd")
    if cost is not None:
        lines.append("")
        lines.append(f"_Ranking cost: ${cost:.4f}_")
    return "\n".join(lines)
