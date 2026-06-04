from __future__ import annotations

import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from . import auth as _auth
from .auth import Principal, current_principal
from .schemas import (
    Application,
    ApplicationCreate,
    ApplicationUpdate,
    EvalCorrectionIn,
    EvalCorrectionOut,
    JobDetail,
    JobListResponse,
    JobSummary,
    ManualJobCreate,
)

load_dotenv()

log = logging.getLogger(__name__)

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

    if os.environ.get(_auth.BYPASS_VAR) == "1":
        log.warning("auth: bypass (dev) — do not use in production")
    else:
        emails = _auth.load_auth_config()
        _auth.init(emails)
        log.info("auth: enforced (allowlist=%d entries)", len(emails))

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
Auth = Annotated[Principal, Depends(current_principal)]

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
    principal: Auth,
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


@router.post("/jobs", response_model=Application, status_code=201)
async def create_manual_job(body: ManualJobCreate, pool: Pool, principal: Auth):
    key = "|".join(
        [
            (body.title or "").lower().strip(),
            (body.company or "").lower().strip(),
            (body.source_url or "").lower().strip(),
        ]
    )
    dedup_hash = hashlib.sha256(key.encode()).hexdigest()
    now = datetime.now(UTC)
    run_id = f"manual-{now.strftime('%Y-%m-%d-%H%M%S')}"

    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO raw.scored_job_postings
                (dedup_hash, title, company, source_url, description, location, posted_at,
                 fit_score, run_id, scored_at, model, provider, profile_version)
            VALUES
                (%(dedup_hash)s, %(title)s, %(company)s, %(source_url)s,
                %(description)s, %(location)s, %(posted_at)s,
                 %(fit_score)s, %(run_id)s, %(scored_at)s,
                 'user', 'user', 'user')
            ON CONFLICT (dedup_hash) DO NOTHING
            """,
            {
                "dedup_hash": dedup_hash,
                "title": body.title,
                "company": body.company,
                "source_url": body.source_url,
                "description": body.description,
                "location": body.location,
                "posted_at": body.posted_at,
                "fit_score": body.fit_score,
                "run_id": run_id,
                "scored_at": now,
            },
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=409, detail="Job already exists")

        cur = await conn.execute(
            """
            INSERT INTO app.user_applications (dedup_hash, status)
            VALUES (%(dedup_hash)s, %(status)s)
            ON CONFLICT (dedup_hash) DO UPDATE
                SET status = EXCLUDED.status, updated_at = now()
            RETURNING dedup_hash, status, applied_at, notes, created_at, updated_at
            """,
            {"dedup_hash": dedup_hash, "status": body.status},
        )
        app_row = cast(dict[str, Any], await cur.fetchone())

    app_row["title"] = body.title
    app_row["company"] = body.company
    app_row["fit_score"] = body.fit_score
    app_row["source_url"] = body.source_url
    return Application.model_validate(app_row)


@router.get("/jobs/{dedup_hash}", response_model=JobDetail)
async def get_job(dedup_hash: str, pool: Pool, principal: Auth):
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
async def list_applications(pool: Pool, principal: Auth):
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
async def create_application(body: ApplicationCreate, pool: Pool, principal: Auth):
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


@router.delete("/applications/{dedup_hash}", status_code=204, response_class=Response)
async def delete_application(dedup_hash: str, pool: Pool, principal: Auth):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM app.user_applications WHERE dedup_hash = %(dedup_hash)s",
            {"dedup_hash": dedup_hash},
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Application not found")
    return Response(status_code=204)


@router.patch("/applications/{dedup_hash}", response_model=Application)
async def update_application(
    dedup_hash: str, body: ApplicationUpdate, pool: Pool, principal: Auth
):
    updates = body.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is None:
        raise HTTPException(status_code=422, detail="status cannot be null")
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


# ---------------------------------------------------------------------------
# Eval corrections — dashboard-sourced gold set for skills_fit
# ---------------------------------------------------------------------------

_CORRECTION_COLS = """
    dedup_hash, corrected_score, correction_reason,
    original_score, original_model, profile_version, corrected_at
"""


@router.post("/eval/corrections", response_model=EvalCorrectionOut, status_code=201)
async def upsert_eval_correction(body: EvalCorrectionIn, pool: Pool, principal: Auth):
    """Upsert a human correction to a job's skills_fit score.

    The server snapshots the current AI score/model/profile_version from
    raw.scored_job_postings so the correction stays meaningful even after a
    later re-scoring run with different (model, profile_version). Last-write-
    wins on dedup_hash.
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT fit_score, model, profile_version
            FROM raw.scored_job_postings
            WHERE dedup_hash = %(dedup_hash)s
            """,
            {"dedup_hash": body.dedup_hash},
        )
        job_row = await cur.fetchone()
        if job_row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job_row = cast(dict[str, Any], job_row)

        cur = await conn.execute(
            f"""
            INSERT INTO app.eval_corrections
                (dedup_hash, corrected_score, correction_reason,
                 original_score, original_model, profile_version)
            VALUES
                (%(dedup_hash)s, %(corrected_score)s, %(correction_reason)s,
                 %(original_score)s, %(original_model)s, %(profile_version)s)
            ON CONFLICT (dedup_hash) DO UPDATE
                SET corrected_score   = EXCLUDED.corrected_score,
                    correction_reason = EXCLUDED.correction_reason,
                    original_score    = EXCLUDED.original_score,
                    original_model    = EXCLUDED.original_model,
                    profile_version   = EXCLUDED.profile_version,
                    corrected_at      = now()
            RETURNING {_CORRECTION_COLS}
            """,
            {
                "dedup_hash": body.dedup_hash,
                "corrected_score": body.corrected_score,
                "correction_reason": body.correction_reason,
                "original_score": job_row["fit_score"],
                "original_model": job_row["model"],
                "profile_version": job_row["profile_version"],
            },
        )
        row = await cur.fetchone()
    return EvalCorrectionOut.model_validate(row)


@router.get("/eval/corrections/{dedup_hash}", response_model=EvalCorrectionOut)
async def get_eval_correction(dedup_hash: str, pool: Pool, principal: Auth):
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"""
            SELECT {_CORRECTION_COLS}
            FROM app.eval_corrections
            WHERE dedup_hash = %(dedup_hash)s
            """,
            {"dedup_hash": dedup_hash},
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Correction not found")
    return EvalCorrectionOut.model_validate(row)


@router.delete(
    "/eval/corrections/{dedup_hash}", status_code=204, response_class=Response
)
async def delete_eval_correction(dedup_hash: str, pool: Pool, principal: Auth):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM app.eval_corrections WHERE dedup_hash = %(dedup_hash)s",
            {"dedup_hash": dedup_hash},
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Correction not found")
    return Response(status_code=204)


@router.get("/eval/corrections", response_model=list[EvalCorrectionOut])
async def list_eval_corrections(
    pool: Pool,
    principal: Auth,
    model: Annotated[str | None, Query(max_length=200)] = None,
    profile_version: Annotated[str | None, Query(max_length=100)] = None,
):
    filters: list[str] = []
    params: dict = {}
    if model is not None:
        filters.append("original_model = %(model)s")
        params["model"] = model
    if profile_version is not None:
        filters.append("profile_version = %(profile_version)s")
        params["profile_version"] = profile_version
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = f"""
        SELECT {_CORRECTION_COLS}
        FROM app.eval_corrections
        {where}
        ORDER BY corrected_at DESC
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)  # type: ignore[arg-type]
        rows = await cur.fetchall()
    return [EvalCorrectionOut.model_validate(r) for r in rows]


app.include_router(router)
