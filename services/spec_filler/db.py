"""Postgres logging for spec_filler runs.

Schema (created externally):
- result_tables(run_uuid UUID UQ, raw_material TEXT, table_name TEXT UQ, characteristics JSONB, companies JSONB, created_at)
- runs(run_uuid FK, company_name, model, input/output/total_tokens, cost_usd, status, error, started_at, finished_at, duration_ms, ...)
- Per-run dynamic table `run_<uuid12>` with columns: company PK + one JSONB column per characteristic
  (each JSONB cell = {"value": str|None, "source_url": str|None, "status": "found"|"not_found"}).
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from .product_spec import CompanyProductSpec, ProductQuery

load_dotenv()
logger = logging.getLogger(__name__)


_LOG_DB_ENV = "SPEC_LOG_DATABASE_URL"


def db_enabled() -> bool:
    # Dedicated env var so we don't accidentally touch the host project's DATABASE_URL
    # (makeathon's DATABASE_URL points to the products DB, not our run-log DB).
    return bool(os.getenv(_LOG_DB_ENV))


@contextmanager
def _conn() -> Iterator[psycopg2.extensions.connection]:
    url = os.getenv(_LOG_DB_ENV)
    if not url:
        raise RuntimeError(f"{_LOG_DB_ENV} is not set")
    c = psycopg2.connect(url)
    try:
        yield c
    finally:
        c.close()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "c_" + s
    return s[:50]  # pg ident limit is 63; leave room for collision suffix


def _make_unique_slugs(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for n in names:
        base = _slug(n)
        if base in seen:
            seen[base] += 1
            out.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 1
            out.append(base)
    return out


def init_run(query: ProductQuery) -> tuple[uuid.UUID, str, list[dict]]:
    """Create the result_tables row and the per-run dynamic table. Return (run_uuid, table_name, char_mapping).

    char_mapping is a list of {"original": str, "slug": str} aligned with query.characteristics.
    """
    run_uuid = uuid.uuid4()
    table_name = f"run_{run_uuid.hex[:16]}"
    slugs = _make_unique_slugs(query.characteristics)
    char_mapping = [
        {"original": orig, "slug": slug}
        for orig, slug in zip(query.characteristics, slugs)
    ]

    columns_ddl = ",\n  ".join(f'"{slug}" JSONB' for slug in slugs)
    create_sql = (
        f'CREATE TABLE "{table_name}" (\n'
        f'  company TEXT PRIMARY KEY,\n'
        f'  {columns_ddl},\n'
        f'  created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n'
        f')'
    )

    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO result_tables (run_uuid, raw_material, table_name, characteristics, companies)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                str(run_uuid),
                query.raw_material_name,
                table_name,
                psycopg2.extras.Json(char_mapping),
                psycopg2.extras.Json(list(query.companies)),
            ),
        )
        cur.execute(create_sql)
        c.commit()

    logger.info("DB: run %s initialized (table=%s)", run_uuid, table_name)
    return run_uuid, table_name, char_mapping


def record_company_run(
    run_uuid: uuid.UUID,
    raw_material: str,
    company: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    error: str | None = None,
) -> None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runs (
                run_uuid, raw_material, company_name, model,
                input_tokens, output_tokens, cost_usd,
                status, error, started_at, finished_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(run_uuid), raw_material, company, model,
                input_tokens, output_tokens, cost_usd,
                status, error, started_at, finished_at,
            ),
        )
        c.commit()


def write_cells(
    table_name: str,
    spec: CompanyProductSpec,
    char_mapping: list[dict],
) -> None:
    """Upsert one row (one company) into the per-run dynamic table. JSONB per cell."""
    slug_by_orig = {m["original"]: m["slug"] for m in char_mapping}

    cell_by_slug: dict[str, dict] = {}
    for c in spec.characteristics:
        slug = slug_by_orig.get(c.name)
        if not slug:
            logger.warning("Unknown characteristic (not in mapping) skipped: %s", c.name)
            continue
        cell_by_slug[slug] = {
            "value": c.value,
            "source_url": c.source_url,
            "status": c.status,
        }

    if not cell_by_slug:
        return

    slugs = list(cell_by_slug.keys())
    quoted_cols = ", ".join(['"company"'] + [f'"{s}"' for s in slugs])
    placeholders = ", ".join(["%s"] * (1 + len(slugs)))
    updates = ", ".join(f'"{s}" = EXCLUDED."{s}"' for s in slugs)

    sql = (
        f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders}) '
        f'ON CONFLICT (company) DO UPDATE SET {updates}'
    )
    values = [spec.company] + [psycopg2.extras.Json(cell_by_slug[s]) for s in slugs]

    with _conn() as c, c.cursor() as cur:
        cur.execute(sql, values)
        c.commit()
