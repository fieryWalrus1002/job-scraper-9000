"""Endpoint tests for GET /api/health, /api/jobs, /api/jobs/{hash}.

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.conftest import (
    FAKE_DETAIL_ROW,
    FAKE_JOB_ROW,
    setup_detail_response,
    setup_list_response,
)


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


async def test_health_returns_200(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


# ---------------------------------------------------------------------------
# GET /api/jobs — response envelope
# ---------------------------------------------------------------------------


async def test_jobs_envelope_shape(client: AsyncClient, fake_conn) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"total", "limit", "offset", "items"}
    assert body["total"] == 1
    assert len(body["items"]) == 1


async def test_jobs_empty_result(client: AsyncClient, fake_conn) -> None:
    setup_list_response(fake_conn, [], total=0)
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_jobs_excludes_application_rows_by_default(
    client: AsyncClient, fake_conn
) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200

    count_sql = fake_conn.execute.await_args_list[0].args[0]
    list_sql = fake_conn.execute.await_args_list[1].args[0]
    combined_sql = f"{count_sql}\n{list_sql}"
    assert "LEFT JOIN app.user_applications a" in combined_sql
    assert "a.user_id = s.user_id" in combined_sql
    assert "a.dedup_hash = s.dedup_hash" in combined_sql
    assert "a.dedup_hash IS NULL" in combined_sql


async def test_jobs_item_fields(client: AsyncClient, fake_conn) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get("/api/jobs")
    item = resp.json()["items"][0]
    assert item["dedup_hash"] == FAKE_JOB_ROW["dedup_hash"]
    assert item["title"] == "Senior Software Engineer"
    assert item["fit_score"] == 4
    assert item["remote_classification"] == "fully_remote"
    assert item["confidence"] == "high"


async def test_jobs_multiple_rows(client: AsyncClient, fake_conn) -> None:
    second = {**FAKE_JOB_ROW, "dedup_hash": "cafebabe" * 8, "fit_score": 2}
    setup_list_response(fake_conn, [FAKE_JOB_ROW, second], total=2)
    resp = await client.get("/api/jobs")
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


# ---------------------------------------------------------------------------
# GET /api/jobs — query param validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "param,value",
    [
        ("min_score", "0"),
        ("min_score", "6"),
        ("max_score", "0"),
        ("max_score", "6"),
        ("limit", "0"),
        ("limit", "1001"),
        ("offset", "-1"),
        ("sort", "bogus"),
        ("sort", "scored_at"),  # intentionally not a sortable key
        ("order", "sideways"),
    ],
)
async def test_jobs_invalid_params_return_422(
    client: AsyncClient, fake_conn, param: str, value: str
) -> None:
    setup_list_response(fake_conn, [])
    resp = await client.get("/api/jobs", params={param: value})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "param,value",
    [
        ("mode", "invalid"),
        ("seed", "-1"),
        ("seed", "2147483648"),
    ],
)
async def test_jobs_grabbag_invalid_params_return_422(
    client: AsyncClient, fake_conn, param: str, value: str
) -> None:
    setup_list_response(fake_conn, [])
    resp = await client.get("/api/jobs", params={param: value})
    assert resp.status_code == 422


async def test_jobs_valid_score_filter(client: AsyncClient, fake_conn) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get("/api/jobs", params={"min_score": "4", "max_score": "5"})
    assert resp.status_code == 200


async def test_jobs_valid_date_filter(client: AsyncClient, fake_conn) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get(
        "/api/jobs",
        params={"min_posted_at": "2026-01-01", "max_posted_at": "2026-12-31"},
    )
    assert resp.status_code == 200


async def test_jobs_valid_remote_classification_filter(
    client: AsyncClient, fake_conn
) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get(
        "/api/jobs", params={"remote_classification": "fully_remote"}
    )
    assert resp.status_code == 200


async def test_jobs_pagination_params_reflected(client: AsyncClient, fake_conn) -> None:
    setup_list_response(fake_conn, [], total=0)
    resp = await client.get("/api/jobs", params={"limit": "10", "offset": "20"})
    body = resp.json()
    assert body["limit"] == 10
    assert body["offset"] == 20


# ---------------------------------------------------------------------------
# GET /api/jobs — sorting
# ---------------------------------------------------------------------------


def _list_sql(fake_conn) -> str:
    """The list SELECT is the second execute() call (the first is the count)."""
    return " ".join(fake_conn.execute.call_args_list[1][0][0].split())


async def test_jobs_default_sort_is_fit_score_desc(
    client: AsyncClient, fake_conn
) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    assert (
        "ORDER BY s.fit_score DESC NULLS LAST, s.scored_at DESC, p.dedup_hash"
        in _list_sql(fake_conn)
    )


@pytest.mark.parametrize(
    "sort,order,expected_col,expected_dir",
    [
        ("fit_score", "asc", "s.fit_score", "ASC"),
        ("posted_at", "desc", "p.posted_at", "DESC"),
        ("company", "asc", "p.company", "ASC"),
        ("title", "desc", "p.title", "DESC"),
        ("salary_min_usd", "asc", "p.salary_min_usd", "ASC"),
    ],
)
async def test_jobs_sort_builds_whitelisted_order_by(
    client: AsyncClient, fake_conn, sort, order, expected_col, expected_dir
) -> None:
    setup_list_response(fake_conn, [FAKE_JOB_ROW])
    resp = await client.get("/api/jobs", params={"sort": sort, "order": order})
    assert resp.status_code == 200
    sql = _list_sql(fake_conn)
    # Primary sort is the whitelisted column + direction, with a stable tiebreaker.
    assert (
        f"ORDER BY {expected_col} {expected_dir} NULLS LAST, s.scored_at DESC, p.dedup_hash"
        in sql
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{dedup_hash} — detail
# ---------------------------------------------------------------------------


async def test_job_detail_returns_full_record(client: AsyncClient, fake_conn) -> None:
    setup_detail_response(fake_conn, FAKE_DETAIL_ROW)
    resp = await client.get(f"/api/jobs/{FAKE_DETAIL_ROW['dedup_hash']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dedup_hash"] == FAKE_DETAIL_ROW["dedup_hash"]
    assert body["source"] == "linkedin"
    assert body["model"] == "claude-sonnet-4-6"
    assert isinstance(body["ai_fit_detail"], dict)
    assert isinstance(body["pipeline_metadata"], dict)


async def test_job_detail_404_on_unknown_hash(client: AsyncClient, fake_conn) -> None:
    setup_detail_response(fake_conn, None)
    resp = await client.get("/api/jobs/notarealhash")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


# ---------------------------------------------------------------------------
# Route contract — all expected paths must be registered
# ---------------------------------------------------------------------------


async def test_route_contract(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = set(resp.json()["paths"].keys())
    expected = {
        "/api/health",
        "/api/jobs",
        "/api/jobs/{dedup_hash}",
        "/api/applications",
        "/api/applications/{dedup_hash}",
        "/api/eval/corrections",
        "/api/eval/corrections/{dedup_hash}",
    }
    assert expected <= paths, f"Missing routes: {expected - paths}"


# ---------------------------------------------------------------------------
# Unknown routes — unprefixed paths must not resolve
# ---------------------------------------------------------------------------
async def test_old_unprefixed_health_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 404


async def test_old_unprefixed_jobs_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/jobs")
    assert resp.status_code == 404


async def test_old_unprefixed_applications_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/applications")
    assert resp.status_code == 404


async def test_old_unprefixed_eval_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/eval/corrections")
    assert resp.status_code == 404
