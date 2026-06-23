from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from ..schemas import (
    Application,
    ApplicationCreate,
    ApplicationEvent,
    ApplicationEventPayload,
    ApplicationStatus,
    ApplicationUpdate,
    StatusChangeEvent,
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


# ---------------------------------------------------------------------------
# Application events sub-resource
# ---------------------------------------------------------------------------


@router.get(
    "/{dedup_hash}/events",
    response_model=list[ApplicationEvent],
)
async def list_events(
    dedup_hash: str,
    pool: Pool,
    user: CurrentUser,
):
    sql = """
        SELECT id, dedup_hash, kind, occurred_at, body, tags, metadata, created_at
        FROM app.application_events
        WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
        ORDER BY occurred_at DESC
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, {"user_id": user.id, "dedup_hash": dedup_hash})
        rows = await cur.fetchall()
    return [ApplicationEvent.model_validate(r) for r in rows]


@router.post(
    "/{dedup_hash}/events",
    response_model=ApplicationEvent,
    status_code=201,
)
async def create_event(
    dedup_hash: str,
    body: ApplicationEventPayload,
    pool: Pool,
    user: CurrentUser,
):
    """Create an application event. Accepts the discriminated union
    (StatusChangeEvent | GenericEvent) and persists it row-by-row."""
    if isinstance(body, StatusChangeEvent):
        # status_change: {from, to} goes into metadata; body/tags stay empty
        metadata: dict[str, object] = {
            "from_status": body.from_status,
            "to_status": body.to_status,
        }
        kind: str = "status_change"
        event_body: str | None = None
        tags: list[str] = []
    else:
        # GenericEvent
        kind = "event"
        event_body = body.body
        tags = body.tags
        metadata = body.metadata

    sql = """
        INSERT INTO app.application_events
            (user_id, dedup_hash, kind, occurred_at, body, tags, metadata)
        VALUES
            (%(user_id)s, %(dedup_hash)s, %(kind)s, %(occurred_at)s, %(body)s, %(tags)s, %(metadata)s::jsonb)
        RETURNING id, dedup_hash, kind, occurred_at, body, tags, metadata, created_at
    """
    params: dict[str, object] = {
        "user_id": user.id,
        "dedup_hash": dedup_hash,
        "kind": kind,
        "occurred_at": None,  # DB default: now()
        "body": event_body,
        "tags": tags,
        "metadata": metadata,
    }
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        row = await cur.fetchone()
    return ApplicationEvent.model_validate(row)


@router.patch("/{dedup_hash}/events/{event_id}", response_model=ApplicationEvent)
async def update_event(
    dedup_hash: str,
    event_id: str,
    body: dict[str, object],
    pool: Pool,
    user: CurrentUser,
):
    """Patch an application event. Allowed fields: occurred_at, body, tags, metadata."""
    allowed = {"occurred_at", "body", "tags", "metadata"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
    params = {
        "event_id": event_id,
        "user_id": user.id,
        "dedup_hash": dedup_hash,
        **updates,
    }
    sql = f"""
        UPDATE app.application_events
        SET {set_clause}
        WHERE id = %(event_id)s AND user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
        RETURNING id, dedup_hash, kind, occurred_at, body, tags, metadata, created_at
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)  # type: ignore[arg-type]
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return ApplicationEvent.model_validate(row)


@router.delete(
    "/{dedup_hash}/events/{event_id}", status_code=204, response_class=Response
)
async def delete_event(
    dedup_hash: str,
    event_id: str,
    pool: Pool,
    user: CurrentUser,
):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM app.application_events "
            "WHERE id = %(event_id)s AND user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s",
            {"event_id": event_id, "user_id": user.id, "dedup_hash": dedup_hash},
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Event not found")
    return Response(status_code=204)
