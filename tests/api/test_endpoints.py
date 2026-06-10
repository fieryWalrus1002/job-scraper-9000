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
    ],
)
async def test_jobs_invalid_params_return_422(
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
# Unknown routes
# ---------------------------------------------------------------------------
async def test_old_unprefixed_health_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 404


async def test_old_unprefixed_jobs_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/jobs")
    assert resp.status_code == 404
