from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from psycopg import AsyncConnection
from psycopg.types.json import Json

from ..schemas import (
    Application,
    ApplicationCreate,
    ApplicationEvent,
    ApplicationEventPayload,
    ApplicationEventUpdate,
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


async def _emit_status_change(
    conn: AsyncConnection[Any],
    *,
    user_id: UUID,
    dedup_hash: str,
    from_status: ApplicationStatus | None,
    to_status: ApplicationStatus,
) -> None:
    """Insert an auto-emitted status_change event. Call inside the same
    transaction as the status write so the two commit atomically.

    occurred_at is omitted so the column DEFAULT now() applies (auto-events are
    not backdatable, §3.2.3). metadata is wrapped in Json() — psycopg cannot
    adapt a bare dict to jsonb.
    """
    await conn.execute(
        """
        INSERT INTO app.application_events (user_id, dedup_hash, kind, metadata)
        VALUES (%(user_id)s, %(dedup_hash)s, 'status_change', %(metadata)s::jsonb)
        """,
        {
            "user_id": user_id,
            "dedup_hash": dedup_hash,
            "metadata": Json({"from_status": from_status, "to_status": to_status}),
        },
    )


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
            p.title, p.company, s.fit_score, p.source_url,
            le.latest_event
        FROM app.user_applications a
        {_JOINS}
        LEFT JOIN LATERAL (
            SELECT json_build_object(
                'kind', e.kind,
                'occurred_at', e.occurred_at,
                'body', e.body,
                'to_status', e.metadata->>'to_status'
            ) AS latest_event
            FROM app.application_events e
            WHERE e.user_id = a.user_id AND e.dedup_hash = a.dedup_hash
            ORDER BY e.occurred_at DESC
            LIMIT 1
        ) le ON true
        {where}
        ORDER BY a.updated_at DESC
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)  # type: ignore[arg-type]
        rows = await cur.fetchall()
    return [Application.model_validate(r) for r in rows]


@router.post("", response_model=Application, status_code=201)
async def create_application(body: ApplicationCreate, pool: Pool, user: CurrentUser):
    insert_params = {**body.model_dump(), "user_id": user.id}
    new_status = insert_params["status"]

    # Read prior status to distinguish insert vs update and detect status change.
    # A NULL result means this is a brand-new row.
    select_sql = """
        SELECT status FROM app.user_applications
        WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
    """
    upsert_sql = """
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
        async with conn.transaction():
            # Read old status (None = new row)
            cur = await conn.execute(select_sql, insert_params)  # type: ignore[arg-type]
            old_row = cast(dict[str, Any] | None, await cur.fetchone())
            old_status: ApplicationStatus | None = (
                old_row["status"] if old_row else None
            )

            # Upsert the application
            cur = await conn.execute(upsert_sql, insert_params)  # type: ignore[arg-type]
            row = await cur.fetchone()

            # Emit a status_change event atomically: new row enters the funnel
            # (from = null); an existing row only when status actually changes.
            if old_status != new_status:
                await _emit_status_change(
                    conn,
                    user_id=user.id,
                    dedup_hash=body.dedup_hash,
                    from_status=old_status,
                    to_status=new_status,
                )

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

    # "status" in updates means the caller sent a status value
    # (model_dump(exclude_unset=True) omits fields not in the request body).

    select_old_sql = """
        SELECT status FROM app.user_applications
        WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
    """
    update_sql = f"""
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
        async with conn.transaction():
            # Read old status before the update
            cur = await conn.execute(select_old_sql, updates)  # type: ignore[arg-type]
            old_row = cast(dict[str, Any] | None, await cur.fetchone())
            if old_row is None:
                raise HTTPException(status_code=404, detail="Application not found")
            old_status = old_row["status"]

            # Apply the update
            cur = await conn.execute(update_sql, updates)  # type: ignore[arg-type]
            row = await cur.fetchone()

            # Emit status_change event only if status actually changed
            if "status" in updates and old_status != updates["status"]:
                await _emit_status_change(
                    conn,
                    user_id=user.id,
                    dedup_hash=dedup_hash,
                    from_status=old_status,
                    to_status=updates["status"],
                )

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

    # occurred_at: only set the column when the caller provides one (backdating).
    # Omitting it from the INSERT lets the column DEFAULT now() apply — passing an
    # explicit NULL would violate the NOT NULL constraint instead.
    cols = ["user_id", "dedup_hash", "kind", "body", "tags", "metadata"]
    params: dict[str, object] = {
        "user_id": user.id,
        "dedup_hash": dedup_hash,
        "kind": kind,
        "body": event_body,
        "tags": tags,
        # jsonb needs the Json() adapter — a bare dict can't be adapted by psycopg.
        "metadata": Json(metadata),
    }
    if body.occurred_at is not None:
        cols.append("occurred_at")
        params["occurred_at"] = body.occurred_at

    placeholders = ", ".join(
        f"%({c})s::jsonb" if c == "metadata" else f"%({c})s" for c in cols
    )
    sql = f"""
        INSERT INTO app.application_events ({", ".join(cols)})
        VALUES ({placeholders})
        RETURNING id, dedup_hash, kind, occurred_at, body, tags, metadata, created_at
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)  # type: ignore[arg-type]
        row = await cur.fetchone()
    return ApplicationEvent.model_validate(row)


@router.patch("/{dedup_hash}/events/{event_id}", response_model=ApplicationEvent)
async def update_event(
    dedup_hash: str,
    event_id: str,
    body: ApplicationEventUpdate,
    pool: Pool,
    user: CurrentUser,
):
    """Patch an application event. Allowed fields: occurred_at, body, tags, metadata."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    # jsonb needs the Json() adapter; everything else passes through as-is.
    if "metadata" in updates:
        updates["metadata"] = Json(updates["metadata"])

    set_clause = ", ".join(
        f"{k} = %({k})s::jsonb" if k == "metadata" else f"{k} = %({k})s"
        for k in updates
    )
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
