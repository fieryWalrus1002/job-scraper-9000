import hashlib
from datetime import datetime, UTC, date
from typing import Annotated, Literal, Any, cast
from fastapi import APIRouter, HTTPException, Query

from ..dependencies import Pool, CurrentUser
from ..schemas import (
    JobListResponse,
    JobSummary,
    JobDetail,
    ManualJobCreate,
    Application,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Feed queries join shared postings (p) to the current user's scores (s);
# the join itself is the visibility rule — no score row, not your job.
_LIST_COLS = """
    p.dedup_hash AS dedup_hash, p.source, p.source_url, p.title, p.company, p.location,
    p.posted_at, p.remote_classification::TEXT, p.salary_min_usd, p.salary_max_usd,
    p.salary_period, s.fit_score, s.confidence::TEXT, s.score_rationale,
    s.failure_reason, s.scored_at
"""

_DETAIL_COLS = """
    dedup_hash, p.source, p.source_job_id, p.source_url,
    p.title, p.company, p.location, p.posted_at, p.description, p.scraped_at,
    p.remote_classification::TEXT,
    p.salary_min_usd, p.salary_max_usd, p.salary_period,
    s.fit_score, s.confidence::TEXT, s.score_rationale,
    s.ai_fit_detail, p.pipeline_metadata,
    s.run_id, s.scored_at, s.model, s.provider, s.profile_version, s.failure_reason,
    p.metadata, p.ingested_at
"""

_FROM = """
    FROM raw.job_postings p
    JOIN raw.job_scores s USING (dedup_hash)
"""

_LIST_FROM = """
    FROM raw.job_postings p
    JOIN raw.job_scores s USING (dedup_hash)
    LEFT JOIN app.user_applications a
        ON a.user_id = s.user_id AND a.dedup_hash = s.dedup_hash
"""


@router.get("", response_model=JobListResponse)
async def list_jobs(
    pool: Pool,
    user: CurrentUser,
    min_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    max_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    # Superset filter: the remote_with_*_travel values are legacy as of
    # remote_filter SCHEMA_VERSION 3.0.0 (no longer produced), kept here so
    # callers can still filter historical rows that carry them. See
    # specs/remote_filter_simplification.md §5.
    remote_classification: Annotated[
        list[
            Literal[
                "fully_remote",
                "remote_with_quarterly_travel",  # legacy (pre-3.0)
                "remote_with_monthly_travel",  # legacy
                "remote_with_frequent_travel",  # legacy
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
    filters: list[str] = ["s.user_id = %(user_id)s", "a.dedup_hash IS NULL"]
    params: dict = {"user_id": user.id}

    if min_score is not None:
        filters.append("s.fit_score >= %(min_score)s")
        params["min_score"] = min_score
    if max_score is not None:
        filters.append("s.fit_score <= %(max_score)s")
        params["max_score"] = max_score
    if remote_classification:
        filters.append(
            "p.remote_classification = ANY(%(remote_classification)s::raw.remote_classification[])"
        )
        params["remote_classification"] = list(remote_classification)
    if min_posted_at is not None:
        filters.append("p.posted_at >= %(min_posted_at)s")
        params["min_posted_at"] = min_posted_at
    if max_posted_at is not None:
        filters.append("p.posted_at <= %(max_posted_at)s")
        params["max_posted_at"] = max_posted_at
    if min_salary_usd is not None:
        filters.append(
            "(p.salary_min_usd >= %(min_salary_usd)s OR p.salary_min_usd IS NULL)"
        )
        params["min_salary_usd"] = min_salary_usd
    if search is not None:
        filters.append("(p.title ILIKE %(search)s OR p.description ILIKE %(search)s)")
        params["search"] = f"%{search}%"
    if company and company.strip():
        filters.append("p.company ILIKE %(company)s")
        params["company"] = f"%{company.strip()}%"

    where = "WHERE " + " AND ".join(filters)

    count_sql = f"SELECT COUNT(*) AS n {_LIST_FROM} {where}"
    list_sql = f"""
        SELECT {_LIST_COLS}
        {_LIST_FROM}
        {where}
        ORDER BY s.fit_score DESC NULLS LAST, s.scored_at DESC
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


@router.post("", response_model=Application, status_code=201)
async def create_manual_job(body: ManualJobCreate, pool: Pool, user: CurrentUser):
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
        # Posting storage is shared: if another user (or the pipeline) already
        # has this posting, the insert no-ops and we just attach this user.
        await conn.execute(
            """
            INSERT INTO raw.job_postings
                (dedup_hash, title, company, source_url, description, location,
                 posted_at, created_by)
            VALUES
                (%(dedup_hash)s, %(title)s, %(company)s, %(source_url)s,
                 %(description)s, %(location)s, %(posted_at)s, %(created_by)s)
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
                "created_by": user.id,
            },
        )

        # The stub score row makes the posting visible in this user's feed;
        # its conflict is what defines "duplicate" — per user, not global.
        cur = await conn.execute(
            """
            INSERT INTO raw.job_scores
                (user_id, dedup_hash, fit_score, run_id, scored_at,
                 model, provider, profile_version)
            VALUES
                (%(user_id)s, %(dedup_hash)s, %(fit_score)s, %(run_id)s,
                 %(scored_at)s, 'user', 'user', 'user')
            ON CONFLICT (user_id, dedup_hash) DO NOTHING
            """,
            {
                "user_id": user.id,
                "dedup_hash": dedup_hash,
                "fit_score": body.fit_score,
                "run_id": run_id,
                "scored_at": now,
            },
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=409, detail="Job already exists")

        cur = await conn.execute(
            """
            INSERT INTO app.user_applications (user_id, dedup_hash, status)
            VALUES (%(user_id)s, %(dedup_hash)s, %(status)s)
            ON CONFLICT (user_id, dedup_hash) DO UPDATE
                SET status = EXCLUDED.status, updated_at = now()
            RETURNING dedup_hash, status, applied_at, notes, created_at, updated_at
            """,
            {"user_id": user.id, "dedup_hash": dedup_hash, "status": body.status},
        )
        app_row = cast(dict[str, Any], await cur.fetchone())

    app_row["title"] = body.title
    app_row["company"] = body.company
    app_row["fit_score"] = body.fit_score
    app_row["source_url"] = body.source_url
    return Application.model_validate(app_row)


@router.get("/{dedup_hash}", response_model=JobDetail)
async def get_job(dedup_hash: str, pool: Pool, user: CurrentUser):
    sql = f"""
        SELECT {_DETAIL_COLS}
        {_FROM}
        WHERE dedup_hash = %(dedup_hash)s AND s.user_id = %(user_id)s
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, {"dedup_hash": dedup_hash, "user_id": user.id})  # type: ignore[arg-type]
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetail.model_validate(row)
