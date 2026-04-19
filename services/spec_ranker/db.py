"""Postgres logging for ranking runs.

Creates (if missing) two tables:
  rankings      — one row per ranking run
  ranking_rows  — one row per (rank_uuid, company) — either ranked or excluded

Non-blocking: any error is caught by the caller and logged as a warning.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from .models import RankingResult

load_dotenv()
logger = logging.getLogger(__name__)


_LOG_DB_ENV = "SPEC_LOG_DATABASE_URL"


def db_enabled() -> bool:
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


DDL = """
CREATE TABLE IF NOT EXISTS rankings (
    id               BIGSERIAL PRIMARY KEY,
    rank_uuid        UUID NOT NULL UNIQUE,
    run_uuid         UUID,
    raw_material     TEXT NOT NULL,
    reference_company TEXT NOT NULL,
    reference_coverage NUMERIC,
    tokens_in        INTEGER NOT NULL DEFAULT 0,
    tokens_out       INTEGER NOT NULL DEFAULT 0,
    cost_usd         NUMERIC,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ranking_rows (
    id               BIGSERIAL PRIMARY KEY,
    rank_uuid        UUID NOT NULL REFERENCES rankings(rank_uuid) ON DELETE CASCADE,
    company          TEXT NOT NULL,
    rank_position    INTEGER,
    coverage         NUMERIC,
    fit_score        NUMERIC,
    overall_score    NUMERIC,
    verdict          TEXT NOT NULL,
    excluded         BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reason TEXT,
    cells            JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ranking_rows_rank_uuid ON ranking_rows(rank_uuid);
CREATE INDEX IF NOT EXISTS idx_rankings_run_uuid ON rankings(run_uuid);
"""


def ensure_schema() -> None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(DDL)
        c.commit()


def save_ranking(result: RankingResult) -> None:
    ensure_schema()
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rankings (
                rank_uuid, run_uuid, raw_material, reference_company,
                reference_coverage, tokens_in, tokens_out, cost_usd
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.rank_uuid,
                result.run_uuid,
                result.raw_material_name,
                result.reference.company,
                result.reference.coverage,
                result.tokens_in,
                result.tokens_out,
                result.cost_usd,
            ),
        )

        rows_values = []
        for r in result.rankings:
            rows_values.append((
                result.rank_uuid,
                r.company,
                r.rank,
                r.coverage,
                r.fit_score,
                r.overall_score,
                r.verdict,
                False,
                None,
                psycopg2.extras.Json([c.model_dump() for c in r.cells]),
            ))
        for e in result.excluded:
            rows_values.append((
                result.rank_uuid,
                e.company,
                None,
                None,
                None,
                None,
                e.verdict,
                True,
                e.reason,
                psycopg2.extras.Json([c.model_dump() for c in e.cells]),
            ))

        if rows_values:
            cur.executemany(
                """
                INSERT INTO ranking_rows (
                    rank_uuid, company, rank_position,
                    coverage, fit_score, overall_score,
                    verdict, excluded, exclusion_reason, cells
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows_values,
            )
        c.commit()
    logger.info("DB: ranking %s saved (%d ranked, %d excluded)",
                result.rank_uuid, len(result.rankings), len(result.excluded))
