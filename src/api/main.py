from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Literal, cast

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .schemas import (
    APPLICATION_STATUSES,
    Application,
    ApplicationCreate,
    ApplicationUpdate,
    JobDetail,
    JobListResponse,
    JobSummary,
)

load_dotenv()

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
    dedup_hash, source, source_url, title, company, location, posted_at,
    remote_classification::TEXT,
    salary_min_usd, salary_max_usd, salary_period,
    fit_score, confidence::TEXT, score_rationale, failure_reason, scored_at
"""

_DETAIL_COLS = """
    dedup_hash, source, source_job_id, source_url,
    title, company, location, posted_at, description, scraped_at,
    remote_classification::TEXT,
    salary_min_usd, salary_max_usd, salary_period,
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
    min_salary_usd: Annotated[int | None, Query(ge=0)] = None,
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
    if min_salary_usd is not None:
        filters.append(
            "(salary_min_usd >= %(min_salary_usd)s OR salary_min_usd IS NULL)"
        )
        params["min_salary_usd"] = min_salary_usd
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


@router.get("/applications", response_model=list[Application])
async def list_applications(pool: Pool):
    sql = """
        SELECT
            a.dedup_hash, a.status, a.applied_at, a.notes, a.created_at, a.updated_at,
            j.title, j.company, j.fit_score, j.source_url
        FROM app.user_applications a
        LEFT JOIN raw.scored_job_postings j USING (dedup_hash)
        ORDER BY a.updated_at DESC
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql)
        rows = await cur.fetchall()
    return [Application.model_validate(r) for r in rows]


@router.post("/applications", response_model=Application, status_code=201)
async def create_application(body: ApplicationCreate, pool: Pool):
    if body.status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")
    sql = """
        INSERT INTO app.user_applications (dedup_hash, status, applied_at, notes)
        VALUES (%(dedup_hash)s, %(status)s, %(applied_at)s, %(notes)s)
        ON CONFLICT (dedup_hash) DO UPDATE
            SET status     = EXCLUDED.status,
                applied_at = EXCLUDED.applied_at,
                notes      = EXCLUDED.notes,
                updated_at = now()
        RETURNING dedup_hash, status, applied_at, notes, created_at, updated_at
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, body.model_dump())
        row = await cur.fetchone()
    return Application.model_validate(row)


@router.patch("/applications/{dedup_hash}", response_model=Application)
async def update_application(dedup_hash: str, body: ApplicationUpdate, pool: Pool):
    if body.status is not None and body.status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")

    updates: dict = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
    updates["dedup_hash"] = dedup_hash
    sql = f"""
        UPDATE app.user_applications
        SET {set_clause}, updated_at = now()
        WHERE dedup_hash = %(dedup_hash)s
        RETURNING dedup_hash, status, applied_at, notes, created_at, updated_at
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, updates)  # type: ignore[arg-type]
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return Application.model_validate(row)


app.include_router(router)
