"""Applications API routes
- WIP, just scaffolding for now
"""

from fastapi import APIRouter, HTTPException, Response

from api.schemas import Application, ApplicationCreate, ApplicationUpdate
from ..dependencies import Pool, Auth

router = APIRouter(tags=["Applications"])


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
