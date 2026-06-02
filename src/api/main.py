from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .schemas import JobDetail, JobListResponse, JobSummary

_pool: AsyncConnectionPool | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = AsyncConnectionPool(
        _database_url(),
        kwargs={"row_factory": dict_row},
        min_size=2,
        max_size=10,
        open=False,
    )
    await _pool.open()
    yield
    await _pool.close()


app = FastAPI(lifespan=lifespan)

# CORS is a fallback for direct API access (curl, Postman, non-proxied dev).
# Primary path in dev is the Vite proxy; in production, Azure SWA routes /api/*.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api")


async def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Connection pool not initialised")
    return _pool


Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]

_LIST_COLS = """
    dedup_hash, source_url, title, company, location, posted_at,
    remote_classification::TEXT,
    fit_score, confidence::TEXT, score_rationale, failure_reason, scored_at
"""

_DETAIL_COLS = """
    dedup_hash, source, source_job_id, source_url,
    title, company, location, posted_at, description, scraped_at,
    remote_classification::TEXT,
    fit_score, confidence::TEXT, score_rationale,
    ai_fit_detail, pipeline_metadata,
    run_id, scored_at, model, provider, profile_version, failure_reason,
    metadata, ingested_at
"""


@router.get("/health")
def health_check():
    return {"status": "healthy"}


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    pool: Pool,
    min_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    max_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    remote_classification: Annotated[
        list[
            Literal[
                "fully_remote",
                "remote_with_quarterly_travel",
                "remote_with_monthly_travel",
                "remote_with_frequent_travel",
                "hybrid",
                "onsite_disguised",
                "location_restricted",
                "unclear",
            ]
        ]
        | None,
        Query(),
    ] = None,
    min_posted_at: Annotated[date | None, Query()] = None,
    max_posted_at: Annotated[date | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters: list[str] = []
    params: dict = {}

    if min_score is not None:
        filters.append("fit_score >= %(min_score)s")
        params["min_score"] = min_score
    if max_score is not None:
        filters.append("fit_score <= %(max_score)s")
        params["max_score"] = max_score
    if remote_classification:
        filters.append(
            "remote_classification = ANY(%(remote_classification)s::raw.remote_classification[])"
        )
        params["remote_classification"] = list(remote_classification)
    if min_posted_at is not None:
        filters.append("posted_at >= %(min_posted_at)s")
        params["min_posted_at"] = min_posted_at
    if max_posted_at is not None:
        filters.append("posted_at <= %(max_posted_at)s")
        params["max_posted_at"] = max_posted_at
    if search is not None:
        filters.append("(title ILIKE %(search)s OR description ILIKE %(search)s)")
        params["search"] = f"%{search}%"
    if company and company.strip():
        filters.append("company ILIKE %(company)s")
        params["company"] = f"%{company.strip()}%"

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    count_sql = f"SELECT COUNT(*) AS n FROM raw.scored_job_postings {where}"
    list_sql = f"""
        SELECT {_LIST_COLS}
        FROM raw.scored_job_postings
        {where}
        ORDER BY fit_score DESC NULLS LAST, scored_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    params["limit"] = limit
    params["offset"] = offset

    async with pool.connection() as conn:
        cur = await conn.execute(count_sql, params)  # type: ignore[arg-type]
        count_row = await cur.fetchone()
        total = cast(dict[str, Any], count_row)["n"] if count_row else 0
        cur = await conn.execute(list_sql, params)  # type: ignore[arg-type]
        rows = await cur.fetchall()

    return JobListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[JobSummary.model_validate(r) for r in rows],
    )


@router.get("/jobs/{dedup_hash}", response_model=JobDetail)
async def get_job(dedup_hash: str, pool: Pool):
    sql = f"""
        SELECT {_DETAIL_COLS}
        FROM raw.scored_job_postings
        WHERE dedup_hash = %(dedup_hash)s
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, {"dedup_hash": dedup_hash})  # type: ignore[arg-type]
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetail.model_validate(row)


app.include_router(router)
