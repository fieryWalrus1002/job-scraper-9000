from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from ..schemas import (
    Application,
    ApplicationCreate,
    ApplicationStatus,
    ApplicationUpdate,
)
from ..dependencies import Pool, CurrentUser

router = APIRouter(prefix="/applications", tags=["Applications"])

# Joined display fields come from the shared posting plus this user's own
# score row — never another user's.
_JOINS = """
    LEFT JOIN raw.job_postings p USING (dedup_hash)
    LEFT JOIN raw.job_scores s
        ON s.dedup_hash = a.dedup_hash AND s.user_id = a.user_id
"""


@router.get("", response_model=list[Application])
async def list_applications(
    pool: Pool,
    user: CurrentUser,
    status: Annotated[list[ApplicationStatus] | None, Query()] = None,
):
    filters = ["a.user_id = %(user_id)s"]
    params: dict[str, object] = {"user_id": user.id}
    if status:
        filters.append("a.status = ANY(%(statuses)s::text[])")
        params["statuses"] = list(status)

    where = "WHERE " + " AND ".join(filters)
    sql = f"""
        SELECT
            a.dedup_hash, a.status, a.applied_at, a.notes, a.created_at, a.updated_at,
            p.title, p.company, s.fit_score, p.source_url
        FROM app.user_applications a
        {_JOINS}
        {where}
        ORDER BY a.updated_at DESC
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)  # type: ignore[arg-type]
        rows = await cur.fetchall()
    return [Application.model_validate(r) for r in rows]


@router.post("", response_model=Application, status_code=201)
async def create_application(body: ApplicationCreate, pool: Pool, user: CurrentUser):
    sql = """
        INSERT INTO app.user_applications (user_id, dedup_hash, status, applied_at, notes)
        VALUES (%(user_id)s, %(dedup_hash)s, %(status)s, %(applied_at)s, %(notes)s)
        ON CONFLICT (user_id, dedup_hash) DO UPDATE
            SET status     = EXCLUDED.status,
                applied_at = EXCLUDED.applied_at,
                notes      = EXCLUDED.notes,
                updated_at = now()
        RETURNING dedup_hash, status, applied_at, notes, created_at, updated_at
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, {**body.model_dump(), "user_id": user.id})
        row = await cur.fetchone()
    return Application.model_validate(row)


@router.delete("/{dedup_hash}", status_code=204, response_class=Response)
async def delete_application(dedup_hash: str, pool: Pool, user: CurrentUser):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM app.user_applications "
            "WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s",
            {"user_id": user.id, "dedup_hash": dedup_hash},
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Application not found")
    return Response(status_code=204)


@router.patch("/{dedup_hash}", response_model=Application)
async def update_application(
    dedup_hash: str, body: ApplicationUpdate, pool: Pool, user: CurrentUser
):
    updates = body.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is None:
        raise HTTPException(status_code=422, detail="status cannot be null")
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
    updates["dedup_hash"] = dedup_hash
    updates["user_id"] = user.id
    sql = f"""
        WITH updated AS (
            UPDATE app.user_applications
            SET {set_clause}, updated_at = now()
            WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
            RETURNING user_id, dedup_hash, status, applied_at, notes, created_at, updated_at
        )
        SELECT a.dedup_hash, a.status, a.applied_at, a.notes, a.created_at, a.updated_at,
               p.title, p.company, s.fit_score, p.source_url
        FROM updated a
        {_JOINS}
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, updates)  # type: ignore[arg-type]
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return Application.model_validate(row)
