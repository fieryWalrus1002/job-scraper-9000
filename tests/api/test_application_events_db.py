"""Live-Postgres round-trip for the application_events endpoints.

The rest of the API suite mocks the pool, so DB-level behavior — jsonb
adaptation, the ``occurred_at`` NOT NULL DEFAULT, the ``kind`` CHECK — is never
exercised there. These bugs pass the mock suite silently and only fail against a
real database. This module drives the actual endpoints through a fresh
postgres:16-alpine container with all migrations applied.

Run: uv run pytest -m docker tests/api/test_application_events_db.py -v
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api import auth
from api.dependencies import current_user, get_pool
from api.main import app
from api.schemas import User

# Container fixture `fresh_pg` is auto-discovered from conftest; _run_alembic is a helper.
from tests.api.conftest import _run_alembic

pytestmark = pytest.mark.docker

DEDUP = "feedface" * 8
SEED_USER = User(
    id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
    email="events-db@localhost",
    display_name="Events DB",
    role="admin",
)


@pytest.fixture
async def db_client(fresh_pg, monkeypatch):  # type: ignore[no-untyped-def]
    """Migrate a fresh DB, seed a user + application (the events FK target),
    and yield an AsyncClient wired to a real pool against the container."""
    # 0006 refuses to seed without a bootstrap admin; supply one so the fixture
    # doesn't depend on a local (untracked) config/auth.yml being present.
    _run_alembic(
        "head", fresh_pg, extra_env={"BOOTSTRAP_ADMIN_EMAIL": "admin@example.com"}
    )

    async with AsyncConnectionPool(
        fresh_pg, kwargs={"row_factory": dict_row}, open=False
    ) as pool:
        await pool.wait()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.users (id, email, role) "
                "VALUES (%(id)s, %(email)s, %(role)s)",
                {"id": SEED_USER.id, "email": SEED_USER.email, "role": SEED_USER.role},
            )
            await conn.execute(
                "INSERT INTO app.user_applications (user_id, dedup_hash, status) "
                "VALUES (%(uid)s, %(dh)s, 'to_apply')",
                {"uid": SEED_USER.id, "dh": DEDUP},
            )

        monkeypatch.setenv(auth.BYPASS_VAR, "1")
        app.dependency_overrides[get_pool] = lambda: pool
        app.dependency_overrides[current_user] = lambda: SEED_USER
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
        app.dependency_overrides.clear()


async def test_generic_event_roundtrip_with_metadata(db_client: AsyncClient) -> None:
    """POST a generic event with metadata + tags, omitting occurred_at.

    Proves: jsonb metadata round-trips (Json adapter), occurred_at falls back to
    the column DEFAULT now() (not a NOT NULL violation from an explicit NULL)."""
    resp = await db_client.post(
        f"/api/applications/{DEDUP}/events",
        json={
            "kind": "event",
            "body": "Emailed the recruiter",
            "tags": ["contact", "follow_up"],
            "metadata": {"email": "r@example.com"},
        },
    )
    assert resp.status_code == 201, resp.text
    ev = resp.json()
    assert ev["metadata"] == {"email": "r@example.com"}
    assert ev["tags"] == ["contact", "follow_up"]
    assert ev["occurred_at"] is not None  # DEFAULT now() applied


async def test_backdated_occurred_at_is_honored(db_client: AsyncClient) -> None:
    """A caller-supplied occurred_at must be stored (backdating, spec §3.2.3)."""
    resp = await db_client.post(
        f"/api/applications/{DEDUP}/events",
        json={
            "kind": "event",
            "body": "Job posted",
            "occurred_at": "2026-05-13T00:00:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["occurred_at"].startswith("2026-05-13")


async def test_status_change_event_roundtrip(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        f"/api/applications/{DEDUP}/events",
        json={"kind": "status_change", "from": "to_apply", "to": "applied"},
    )
    assert resp.status_code == 201, resp.text
    ev = resp.json()
    assert ev["kind"] == "status_change"
    assert ev["metadata"]["to_status"] == "applied"


async def test_patch_metadata_persists_as_jsonb(db_client: AsyncClient) -> None:
    created = await db_client.post(
        f"/api/applications/{DEDUP}/events",
        json={"kind": "event", "body": "note"},
    )
    event_id = created.json()["id"]
    patched = await db_client.patch(
        f"/api/applications/{DEDUP}/events/{event_id}",
        json={"metadata": {"phone": "555-0100"}, "tags": ["contact"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["metadata"] == {"phone": "555-0100"}


async def test_list_then_delete(db_client: AsyncClient) -> None:
    await db_client.post(
        f"/api/applications/{DEDUP}/events", json={"kind": "event", "body": "a"}
    )
    listed = await db_client.get(f"/api/applications/{DEDUP}/events")
    assert listed.status_code == 200
    event_id = listed.json()[0]["id"]

    deleted = await db_client.delete(f"/api/applications/{DEDUP}/events/{event_id}")
    assert deleted.status_code == 204

    again = await db_client.get(f"/api/applications/{DEDUP}/events")
    assert all(e["id"] != event_id for e in again.json())


# ---------------------------------------------------------------------------
# #381 — auto-emit status_change on triage mutations (real DB)
# ---------------------------------------------------------------------------


async def test_patch_status_auto_emits_status_change(db_client: AsyncClient) -> None:
    """PATCHing the application status writes a status_change event with the
    correct {from,to} — proves the auto-emit INSERT's Json(metadata) adapts and
    the row commits in the same transaction. The seeded app starts at 'to_apply'."""
    resp = await db_client.patch(
        f"/api/applications/{DEDUP}", json={"status": "applied"}
    )
    assert resp.status_code == 200, resp.text

    events = (await db_client.get(f"/api/applications/{DEDUP}/events")).json()
    changes = [e for e in events if e["kind"] == "status_change"]
    assert len(changes) == 1
    assert changes[0]["metadata"] == {"from_status": "to_apply", "to_status": "applied"}


async def test_patch_notes_only_emits_no_event(db_client: AsyncClient) -> None:
    """A notes-only PATCH must not emit a status_change event."""
    resp = await db_client.patch(
        f"/api/applications/{DEDUP}", json={"notes": "called recruiter"}
    )
    assert resp.status_code == 200, resp.text

    events = (await db_client.get(f"/api/applications/{DEDUP}/events")).json()
    assert [e for e in events if e["kind"] == "status_change"] == []
