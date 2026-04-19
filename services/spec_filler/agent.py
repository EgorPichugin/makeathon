import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from . import db
from .product_spec import (
    CompanyProductSpec,
    FilledProductMatrix,
    ProductQuery,
)

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
MAX_PARALLEL_COMPANIES = 2
URL_RESOLVE_TIMEOUT = 10.0
PAGE_FETCH_TIMEOUT = 15.0
MAX_URLS_PER_COMPANY = 3
MAX_CHARS_PER_PAGE = 60_000

# USD per 1M tokens. Source: ai.google.dev/pricing as of 2026-04-18 — update if rates change.
# Grounding (google_search) is billed separately per query; not included here.
PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}

SEARCH_PROMPT = """You are a research assistant locating technical specification documents for a raw material as sold or supplied by a specific company. You MUST use the Google Search tool — do not answer from memory or training data.

Raw material: {raw_material_name}
Company: {company}

MANDATORY PROCEDURE:
1. Perform MULTIPLE Google Search queries. At minimum:
   - "{company} {raw_material_name}"
   - "{company} {raw_material_name} datasheet"
   - "{company} {raw_material_name} spec sheet"
   - "{company} {raw_material_name} COA"
   - "{company} {raw_material_name} technical data sheet"
   - "{company} {raw_material_name} product information"
2. For each query, read the top results and note URLs relevant to technical specifications of this raw material from this specific company.
3. Prefer in this order: (a) the company's own domain, (b) PDF datasheets / COAs / TDS whose URLs contain words like "datasheet", "spec", "TDS", "COA", "technical", (c) reputable distributor directories.
4. Write a research note describing which pages/PDFs you found and briefly what each contains. Include source URLs inline. Aim for at least 400 characters of output — if you write less, you probably didn't actually search enough.

Do NOT output a structured list; free-form text is fine. The URLs we care about will be captured from grounding metadata automatically — we just need you to actually perform the searches.
"""

READ_PROMPT = """You have a URL Context tool that fetches full page content (including PDFs). You MUST invoke it to read EACH URL below. Do NOT answer from memory.

Raw material: {raw_material_name}
Company: {company}

URLs to read — fetch each one via URL Context:
{urls_block}

For every URL, after reading the full page/PDF content:
- Reproduce relevant spec-table rows VERBATIM — exact labels, values, units.
- Include ALL numeric specifications you see on the page (even ones not listed in our characteristics of interest).
- Quote ingredient/carrier lists literally.
- Tag each quoted fact with its source URL in square brackets: [source: https://...].

Our characteristics of interest (for orientation; extract whatever is available):
{characteristics_list}

Format: free-form plain text, organized section-by-section per URL. Target 1500+ characters if the pages contain spec data. Short summaries are failures — we need raw text for downstream structured extraction.
"""

EXTRACT_PROMPT = """Extract specifications for a raw material as offered by a SPECIFIC COMPANY, from research notes.

Raw material: {raw_material_name}
Company: {company}

Characteristics to fill (preserve order and exact names):
{characteristics_list}

=== RESEARCH NOTES ===
{research_text}
=== END RESEARCH NOTES ===

Source URLs seen by the research:
{urls_block}

STRICT SOURCE RULES — apply to every "found" cell:
1. source_url MUST be EITHER:
   (a) on the company's own corporate domain (e.g., for "PureBulk" → purebulk.com; infer the likely domain from the company name), OR
   (b) a distributor / directory / B2B ingredient marketplace page that EXPLICITLY names "{company}" as the supplier of this product variant (not just the chemical in general).
2. General-reference pages (Wikipedia, PubChem, NIH, Healthline, USDA monographs, Mayo Clinic, FDA GRAS, USP) describe the CHEMICAL in general — they are NOT valid sources for a company-specific spec. Even if they list a CAS number or form, you MUST set status="not_found" when that is the only source available for this company.
3. If the research notes contain facts that match a characteristic but the only cited URL is a general-reference page (rule 2), set status="not_found", value=null, source_url=null.

Rules for each characteristic:
- If a valid company-specific source has the value, set status="found", value=<concise value with units>, source_url=<that URL>.
- Otherwise, set status="not_found", value=null, source_url=null.
- NEVER fabricate.
"""



_RESOLVE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def _build_characteristics_list(query: ProductQuery) -> str:
    return "\n".join(f"- {c}" for c in query.characteristics)


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
    """Build a Gemini client. Vertex AI if USE_VERTEX_AI=true, else AI Studio via API key."""
    if _use_vertex():
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError("USE_VERTEX_AI=true requires GOOGLE_CLOUD_PROJECT to be set.")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        logger.info("Using Vertex AI backend (project=%s, location=%s)", project, location)
        return genai.Client(vertexai=True, project=project, location=location)
    logger.info("Using AI Studio backend (API key)")
    return genai.Client(api_key=_api_key())


def _extract_grounding_urls(response) -> list[str]:
    urls: list[str] = []
    try:
        for candidate in response.candidates or []:
            meta = getattr(candidate, "grounding_metadata", None)
            if not meta:
                continue
            for chunk in getattr(meta, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None) if web else None
                if uri and uri not in urls:
                    urls.append(uri)
    except (AttributeError, TypeError) as e:
        logger.warning("Failed to extract grounding URLs: %s", e)
    return urls


def _resolve_url(url: str) -> str:
    """Follow redirects on a Gemini grounding-proxy URL to get the real source URL.

    The proxy (vertexaisearch.cloud.google.com) sometimes serves certs that Homebrew Python's
    trust store can't verify. We first try with strict TLS; on SSL failure we retry with
    verification disabled ONLY for the redirect hop — the final content fetch keeps strict TLS.
    """
    if "vertexaisearch.cloud.google.com" not in url:
        return url
    for verify in (True, False):
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=URL_RESOLVE_TIMEOUT,
                headers=_RESOLVE_HEADERS,
                verify=verify,
            ) as client:
                resp = client.get(url)
                resolved = str(resp.url)
                if not verify:
                    logger.info("URL resolved via insecure TLS fallback: %s", resolved)
                break
        except httpx.ConnectError as e:
            if verify and "CERTIFICATE_VERIFY_FAILED" in str(e):
                continue  # retry with verify=False
            logger.warning("URL resolve failed (kept proxy URL) for %s: %s", url, e)
            return url
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("URL resolve failed (kept proxy URL) for %s: %s", url, e)
            return url
    else:
        return url

    if "vertexaisearch.cloud.google.com" in resolved:
        logger.warning("URL resolve returned proxy URL unchanged for %s", url)
    return resolved


def _fetch_page_text(url: str) -> str | None:
    """Fetch a URL and return its visible text (stripped of scripts/nav/footer). None on failure.

    PDF and non-text responses are skipped — MVP only supports HTML pages.
    Tries strict TLS first; on certificate errors falls back to verify=False so we can still
    read publicly-accessible supplier pages even with CDN cert misconfiguration.
    """
    resp = None
    for verify in (True, False):
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=PAGE_FETCH_TIMEOUT,
                headers=_RESOLVE_HEADERS,
                verify=verify,
            ) as client:
                resp = client.get(url)
                if not verify:
                    logger.info("Page fetched via insecure TLS fallback: %s", url)
            break
        except httpx.ConnectError as e:
            if verify and "CERTIFICATE_VERIFY_FAILED" in str(e):
                logger.info("Strict TLS failed for %s; retrying with verify=False", url)
                continue
            logger.warning("Page fetch failed for %s: %s", url, e)
            return None
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Page fetch failed for %s: %s", url, e)
            return None
    if resp is None:
        return None

    if resp.status_code != 200:
        logger.warning("Page fetch %s returned HTTP %d", url, resp.status_code)
        return None

    content_type = resp.headers.get("content-type", "").lower()
    if "pdf" in content_type:
        logger.warning("Page %s is PDF (MVP skips PDFs)", url)
        return None
    if "html" not in content_type and "text" not in content_type:
        logger.warning("Page %s has non-text content-type: %s", url, content_type)
        return None

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.warning("HTML parse failed for %s: %s", url, e)
        return None

    for tag in soup(["script", "style", "noscript", "iframe", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:MAX_CHARS_PER_PAGE]


def _log_url_context_metadata(company: str, response) -> None:
    try:
        for candidate in response.candidates or []:
            meta = getattr(candidate, "url_context_metadata", None)
            if meta:
                url_meta = getattr(meta, "url_metadata", None) or []
                if url_meta:
                    for m in url_meta:
                        url = getattr(m, "retrieved_url", "?")
                        status = str(getattr(m, "url_retrieval_status", "?"))
                        if "ERROR" in status:
                            logger.warning(
                                "[%s] url_context BLOCKED (likely Cloudflare / anti-bot): %s",
                                company, url,
                            )
                        else:
                            logger.info("[%s] url_context OK: %s [%s]", company, url, status)
                else:
                    logger.warning("[%s] url_context_metadata present but empty", company)
            else:
                logger.warning("[%s] NO url_context_metadata — Gemini did not use URL Context tool", company)
    except (AttributeError, TypeError) as e:
        logger.debug("Could not read url_context_metadata: %s", e)


def _search_urls(
    client: genai.Client, query: ProductQuery, company: str
) -> tuple[list[str], int, int]:
    """Step 1: grounded google_search — returns candidate URLs from grounding_metadata."""
    response = client.models.generate_content(
        model=MODEL,
        contents=SEARCH_PROMPT.format(
            raw_material_name=query.raw_material_name, company=company
        ),
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.0,
        ),
    )

    proxy_urls = _extract_grounding_urls(response)

    resolved: list[str] = []
    if proxy_urls:
        with ThreadPoolExecutor(max_workers=min(len(proxy_urls), 5)) as pool:
            for u in pool.map(_resolve_url, proxy_urls):
                if "vertexaisearch.cloud.google.com" in u:
                    continue
                if u not in resolved:
                    resolved.append(u)

    in_t = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
    out_t = (getattr(response.usage_metadata, "candidates_token_count", 0) or 0) + (
        getattr(response.usage_metadata, "thoughts_token_count", 0) or 0
    )
    return resolved[:MAX_URLS_PER_COMPANY], in_t, out_t


def _read_urls(
    client: genai.Client,
    query: ProductQuery,
    company: str,
    chars_list: str,
    urls: list[str],
) -> tuple[str, int, int]:
    """Step 2: url_context reads the URLs in the prompt and dumps verbatim content.

    No response_schema here — Vertex rejects controlled-generation with url_context.
    """
    urls_block = "\n".join(f"- {u}" for u in urls)
    response = client.models.generate_content(
        model=MODEL,
        contents=READ_PROMPT.format(
            raw_material_name=query.raw_material_name,
            company=company,
            characteristics_list=chars_list,
            urls_block=urls_block,
        ),
        config=types.GenerateContentConfig(
            tools=[types.Tool(url_context=types.UrlContext())],
            temperature=0.0,
        ),
    )

    _log_url_context_metadata(company, response)
    text = response.text or ""
    in_t = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
    out_t = (getattr(response.usage_metadata, "candidates_token_count", 0) or 0) + (
        getattr(response.usage_metadata, "thoughts_token_count", 0) or 0
    )
    return text, in_t, out_t


def _extract_structured(
    client: genai.Client,
    query: ProductQuery,
    company: str,
    chars_list: str,
    research_text: str,
    urls: list[str],
) -> tuple[CompanyProductSpec, int, int]:
    """Step 3: response_schema call (no tools) — converts the dump into structured CompanyProductSpec."""
    if not research_text.strip():
        spec = CompanyProductSpec(
            company=company,
            characteristics=[
                {"name": c, "value": None, "source_url": None, "status": "not_found"}
                for c in query.characteristics
            ],
        )
        return spec, 0, 0

    urls_block = "\n".join(f"- {u}" for u in urls) if urls else "(none)"
    response = client.models.generate_content(
        model=MODEL,
        contents=EXTRACT_PROMPT.format(
            raw_material_name=query.raw_material_name,
            company=company,
            characteristics_list=chars_list,
            research_text=research_text,
            urls_block=urls_block,
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CompanyProductSpec,
            temperature=0.0,
        ),
    )

    raw = response.text or ""
    try:
        spec = CompanyProductSpec.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("[%s] model_validate_json failed (%s), retrying via json.loads", company, e)
        spec = CompanyProductSpec.model_validate(json.loads(raw))

    in_t = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
    out_t = (getattr(response.usage_metadata, "candidates_token_count", 0) or 0) + (
        getattr(response.usage_metadata, "thoughts_token_count", 0) or 0
    )
    return spec, in_t, out_t


def _fetch_pages(urls: list[str]) -> list[tuple[str, str]]:
    """Fetch each URL in parallel. Return list of (url, text) for successful fetches only."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as pool:
        texts = list(pool.map(_fetch_page_text, urls))
    return [(u, t) for u, t in zip(urls, texts) if t]




def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    rates = PRICING.get(model)
    if not rates:
        return None
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def _fmt_cost(cost: float | None) -> str:
    return f"${cost:.6f}" if cost is not None else "n/a (model not in PRICING table)"


def _pipeline(
    client: genai.Client, query: ProductQuery, company: str, chars_list: str
) -> tuple[CompanyProductSpec, int, int]:
    """Three-step pipeline (Vertex requires controlled generation to be separate from url_context):
    1. google_search → candidate URLs from grounding_metadata.
    2. url_context reads URLs listed in the prompt → verbatim dump of page content.
    3. response_schema turns the dump into structured CompanyProductSpec.
    """
    logger.info("[%s] step 1/3: google_search for candidate URLs", company)
    urls, s_in, s_out = _search_urls(client, query, company)
    logger.info("[%s] found %d URLs: %s", company, len(urls), urls)

    if not urls:
        spec, x_in, x_out = _extract_structured(client, query, company, chars_list, "", [])
        return spec, s_in + x_in, s_out + x_out

    logger.info("[%s] step 2/3: url_context reads pages (verbatim dump)", company)
    dump_text, r_in, r_out = _read_urls(client, query, company, chars_list, urls)
    logger.info("[%s] dump size: %d chars", company, len(dump_text))

    logger.info("[%s] step 3/3: structured extract from dump", company)
    spec, x_in, x_out = _extract_structured(client, query, company, chars_list, dump_text, urls)
    return spec, s_in + r_in + x_in, s_out + r_out + x_out


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=60), reraise=True)
def _fill_for_company(
    client: genai.Client,
    query: ProductQuery,
    company: str,
    chars_list: str,
    run_ctx: dict | None,
) -> tuple[CompanyProductSpec, int, int]:
    started_at = datetime.now(timezone.utc)
    logger.info("[%s] starting pipeline", company)
    status = "failed"
    error: str | None = None
    spec: CompanyProductSpec | None = None
    in_tokens = out_tokens = 0

    try:
        spec, in_tokens, out_tokens = _pipeline(client, query, company, chars_list)
        status = "success"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        logger.exception("[%s] pipeline failed", company)
        raise
    finally:
        finished_at = datetime.now(timezone.utc)
        cost = _cost_usd(MODEL, in_tokens, out_tokens)

        if run_ctx:
            try:
                db.record_company_run(
                    run_uuid=run_ctx["run_uuid"],
                    raw_material=query.raw_material_name,
                    company=company,
                    model=MODEL,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    cost_usd=cost,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    error=error,
                )
            except Exception as db_err:
                logger.warning("[%s] runs insert failed (non-fatal): %s", company, db_err)
            if spec is not None:
                try:
                    db.write_cells(run_ctx["table_name"], spec, run_ctx["char_mapping"])
                except Exception as db_err:
                    logger.warning("[%s] cells write failed (non-fatal): %s", company, db_err)

    logger.info(
        "[%s] tokens in=%d out=%d total=%d | cost=%s",
        company, in_tokens, out_tokens, in_tokens + out_tokens, _fmt_cost(cost),
    )
    assert spec is not None
    n_found = sum(1 for c in spec.characteristics if c.status == "found")
    logger.info("[%s] findings: %d/%d", company, n_found, len(spec.characteristics))
    for c in spec.characteristics:
        if c.status == "found":
            logger.info("[%s]   %s = %s  (%s)", company, c.name, c.value, c.source_url)
        else:
            logger.info("[%s]   %s = NOT FOUND", company, c.name)

    return spec, in_tokens, out_tokens


def _init_run_ctx(query: ProductQuery) -> dict | None:
    """Best-effort DB init. Returns context dict or None if DB is disabled or init failed."""
    if not db.db_enabled():
        logger.info("DB logging disabled (DATABASE_URL not set)")
        return None
    try:
        run_uuid, table_name, char_mapping = db.init_run(query)
        return {"run_uuid": run_uuid, "table_name": table_name, "char_mapping": char_mapping}
    except Exception as e:
        logger.warning("DB init failed (continuing without DB logging): %s", e)
        return None


def find_product_info(query: ProductQuery) -> FilledProductMatrix:
    """Fill a raw-material spec matrix (companies × characteristics).

    Pipeline per company (run in parallel, capped at MAX_PARALLEL_COMPANIES):
      1. Grounded Gemini call discovers up to N product-page URLs.
      2. httpx + BeautifulSoup fetch full HTML content of each URL.
      3. Non-grounded Gemini call extracts specs from the fetched text via response_schema.

    If DATABASE_URL is set, each run is persisted to Postgres (result_tables + runs + dynamic JSONB table).
    """
    client = _make_client()
    chars_list = _build_characteristics_list(query)
    run_ctx = _init_run_ctx(query)

    workers = min(MAX_PARALLEL_COMPANIES, max(1, len(query.companies)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(
                lambda c: _fill_for_company(client, query, c, chars_list, run_ctx),
                query.companies,
            )
        )

    specs = [r[0] for r in results]
    total_in = sum(r[1] for r in results)
    total_out = sum(r[2] for r in results)
    total_cost = _cost_usd(MODEL, total_in, total_out)
    logger.info(
        "TOTAL for '%s' across %d companies: tokens in=%d out=%d total=%d | cost=%s",
        query.raw_material_name, len(query.companies),
        total_in, total_out, total_in + total_out, _fmt_cost(total_cost),
    )

    return FilledProductMatrix(
        raw_material_name=query.raw_material_name,
        companies=specs,
        run_uuid=str(run_ctx["run_uuid"]) if run_ctx else None,
        table_name=run_ctx["table_name"] if run_ctx else None,
    )
