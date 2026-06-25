"""Live-Postgres round-trip for grab-bag mode on GET /jobs.

The rest of the API suite mocks the pool, so the weighted-sampling SQL
(``hashtextextended``, ``power(u, 1.0/fit_score)``, the floor/NULL/triaged
exclusions) is never exercised there — a broken query passes the mock suite
silently. This module drives the real endpoint through a fresh
postgres:16-alpine container with all migrations applied.

Run: uv run pytest -m docker tests/api/test_grabbag_db.py -v
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

SEED_USER = User(
    id=uuid.UUID("00000000-0000-0000-0000-0000000000bb"),
    email="grabbag-db@localhost",
    display_name="Grab Bag DB",
    role="admin",
)

# Seven postings: fit 5/4/3 (above floor), fit 2/1 (below default floor of 3),
# one NULL fit (unscored), and one fit-5 that is already triaged. Only fit3/4/5
# should ever enter a grab bag with the default floor.
_POSTINGS = [
    ("hash-fit5", "Fit 5 Job", "A", "http://x/1", "2026-01-01"),
    ("hash-fit4", "Fit 4 Job", "B", "http://x/2", "2026-01-02"),
    ("hash-fit3", "Fit 3 Job", "C", "http://x/3", "2026-01-03"),
    ("hash-fit2", "Fit 2 Job", "D", "http://x/4", "2026-01-04"),
    ("hash-fit1", "Fit 1 Job", "E", "http://x/5", "2026-01-05"),
    ("hash-null", "Null Job", "F", "http://x/6", "2026-01-06"),
    ("hash-triaged", "Tria Job", "G", "http://x/7", "2026-01-07"),
]
_SCORES = [
    ("hash-fit5", 5),
    ("hash-fit4", 4),
    ("hash-fit3", 3),
    ("hash-fit2", 2),
    ("hash-fit1", 1),
    ("hash-null", None),
    ("hash-triaged", 5),
]


@pytest.fixture
async def db_client(fresh_pg, monkeypatch):  # type: ignore[no-untyped-def]
    """Migrate a fresh DB, seed a user + the varied-fit postings/scores (with one
    triaged job), and yield an AsyncClient wired to a real pool."""
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
            for dedup_hash, title, company, url, posted_at in _POSTINGS:
                await conn.execute(
                    "INSERT INTO raw.job_postings "
                    "(dedup_hash, title, company, source, source_url, posted_at, "
                    " remote_classification, created_by) "
                    "VALUES (%(dh)s, %(title)s, %(company)s, 'test', %(url)s, "
                    "        %(posted_at)s, 'fully_remote', %(uid)s)",
                    {
                        "dh": dedup_hash,
                        "title": title,
                        "company": company,
                        "url": url,
                        "posted_at": posted_at,
                        "uid": SEED_USER.id,
                    },
                )
            for dedup_hash, fit_score in _SCORES:
                # NOT NULL DEFAULT columns are omitted; fit_score is nullable so an
                # explicit NULL is the intended "unscored" signal here.
                await conn.execute(
                    "INSERT INTO raw.job_scores "
                    "(user_id, dedup_hash, fit_score, run_id, scored_at, "
                    " model, provider, profile_version) "
                    "VALUES (%(uid)s, %(dh)s, %(fit)s, 'run-1', now(), 'm', 'p', 'v1')",
                    {"uid": SEED_USER.id, "dh": dedup_hash, "fit": fit_score},
                )
            # hash-triaged gains an application row → leaves the untriaged pool.
            await conn.execute(
                "INSERT INTO app.user_applications (user_id, dedup_hash, status) "
                "VALUES (%(uid)s, 'hash-triaged', 'maybe')",
                {"uid": SEED_USER.id},
            )

        monkeypatch.setenv(auth.BYPASS_VAR, "1")
        app.dependency_overrides[get_pool] = lambda: pool
        app.dependency_overrides[current_user] = lambda: SEED_USER
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
        app.dependency_overrides.clear()


async def _grabbag_hashes(client: AsyncClient, **params: object) -> list[str]:
    resp = await client.get("/api/jobs", params={"mode": "grabbag", **params})
    assert resp.status_code == 200, resp.text
    return [item["dedup_hash"] for item in resp.json()["items"]]


async def test_grabbag_is_deterministic_per_seed(db_client: AsyncClient) -> None:
    """Same seed ⇒ same batch (the seed is the stable shuffle order, spec §3.3)."""
    first = await _grabbag_hashes(db_client, seed=42)
    again = await _grabbag_hashes(db_client, seed=42)
    assert first == again


async def test_grabbag_excludes_below_floor_null_and_triaged(
    db_client: AsyncClient,
) -> None:
    """Default floor=3 admits only fit3/4/5; NULL fit and triaged jobs never appear."""
    hashes = set(await _grabbag_hashes(db_client, seed=42))
    assert hashes <= {"hash-fit3", "hash-fit4", "hash-fit5"}
    assert "hash-fit2" not in hashes  # below floor
    assert "hash-fit1" not in hashes  # below floor
    assert "hash-null" not in hashes  # unscored (fit_score IS NULL)
    assert "hash-triaged" not in hashes  # has an application row


async def test_grabbag_size_defaults_to_20_without_config(
    db_client: AsyncClient,
) -> None:
    """With no user_search_configs row, the bag is sized by the migration-0016
    default (20), NOT the table-mode `limit` default (500)."""
    resp = await db_client.get("/api/jobs", params={"mode": "grabbag", "seed": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["limit"] == 20


async def test_grabbag_rejects_nonzero_offset(db_client: AsyncClient) -> None:
    """Grab-bag mode is not paged; an explicit offset must fail loud, not be ignored."""
    resp = await db_client.get(
        "/api/jobs", params={"mode": "grabbag", "seed": 1, "offset": 20}
    )
    assert resp.status_code == 400, resp.text
    assert "offset" in resp.json()["detail"]


async def test_grabbag_honors_score_filters(db_client: AsyncClient) -> None:
    """Existing filters still apply in grab-bag mode (a user can constrain the bag)."""
    resp = await db_client.get(
        "/api/jobs",
        params={"mode": "grabbag", "seed": 0, "min_score": 5, "max_score": 5},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert all(item["fit_score"] == 5 for item in items)
    assert {item["dedup_hash"] for item in items} <= {"hash-fit5"}


async def test_grabbag_different_seeds_sample_same_pool(db_client: AsyncClient) -> None:
    """A different seed reshuffles, but never leaves the untriaged above-floor pool."""
    other = set(await _grabbag_hashes(db_client, seed=9999))
    assert other <= {"hash-fit3", "hash-fit4", "hash-fit5"}


async def test_table_mode_unchanged(db_client: AsyncClient) -> None:
    """mode=table keeps its shape (the grab-bag branch must not affect it)."""
    resp = await db_client.get("/api/jobs", params={"mode": "table"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total" in body and "items" in body
    # Table mode shows every untriaged job (no floor), triaged excluded.
    table_hashes = {item["dedup_hash"] for item in body["items"]}
    assert "hash-triaged" not in table_hashes
    assert "hash-fit1" in table_hashes  # no floor in table mode
