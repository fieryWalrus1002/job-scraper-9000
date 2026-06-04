"""Endpoint tests for /api/eval/corrections.

All tests use the mock pool fixture — no live Postgres required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from tests.api.conftest import FAKE_JOB_ROW, _make_cursor

FAKE_CORRECTION_ROW: dict[str, Any] = {
    "dedup_hash": FAKE_JOB_ROW["dedup_hash"],
    "corrected_score": 2,
    "correction_reason": "Overweighted FPGA experience — this is firmware-adjacent only.",
    "original_score": 4,
    "original_model": "qwen3-coder:30b",
    "profile_version": "v3",
    "corrected_at": datetime(2026, 6, 3, 18, 45, 0),
}

FAKE_SNAPSHOT_ROW: dict[str, Any] = {
    "fit_score": 4,
    "model": "qwen3-coder:30b",
    "profile_version": "v3",
}


# ---------------------------------------------------------------------------
# POST /api/eval/corrections (upsert)
# ---------------------------------------------------------------------------


async def test_upsert_eval_correction(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    snapshot_cur = _make_cursor(FAKE_SNAPSHOT_ROW)
    upsert_cur = _make_cursor(FAKE_CORRECTION_ROW)
    fake_conn.execute = AsyncMock(side_effect=[snapshot_cur, upsert_cur])

    resp = await client.post(
        "/api/eval/corrections",
        json={
            "dedup_hash": FAKE_JOB_ROW["dedup_hash"],
            "corrected_score": 2,
            "correction_reason": "Overweighted FPGA experience — this is firmware-adjacent only.",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["corrected_score"] == 2
    assert data["original_score"] == 4
    assert data["original_model"] == "qwen3-coder:30b"
    assert data["profile_version"] == "v3"


async def test_upsert_eval_correction_minimal_body(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    """Reason is optional."""
    row = {**FAKE_CORRECTION_ROW, "correction_reason": None}
    fake_conn.execute = AsyncMock(
        side_effect=[_make_cursor(FAKE_SNAPSHOT_ROW), _make_cursor(row)]
    )
    resp = await client.post(
        "/api/eval/corrections",
        json={"dedup_hash": FAKE_JOB_ROW["dedup_hash"], "corrected_score": 5},
    )
    assert resp.status_code == 201
    assert resp.json()["correction_reason"] is None


async def test_upsert_eval_correction_job_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(None))
    resp = await client.post(
        "/api/eval/corrections",
        json={"dedup_hash": "nonexistent", "corrected_score": 2},
    )
    assert resp.status_code == 404


async def test_upsert_eval_correction_score_below_range(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.post(
        "/api/eval/corrections",
        json={"dedup_hash": FAKE_JOB_ROW["dedup_hash"], "corrected_score": 0},
    )
    assert resp.status_code == 422


async def test_upsert_eval_correction_score_above_range(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    resp = await client.post(
        "/api/eval/corrections",
        json={"dedup_hash": FAKE_JOB_ROW["dedup_hash"], "corrected_score": 6},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/eval/corrections/{dedup_hash}
# ---------------------------------------------------------------------------


async def test_get_eval_correction(client: AsyncClient, fake_conn: AsyncMock) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_CORRECTION_ROW))
    resp = await client.get(f"/api/eval/corrections/{FAKE_JOB_ROW['dedup_hash']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["corrected_score"] == 2
    assert data["original_model"] == "qwen3-coder:30b"


async def test_get_eval_correction_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(None))
    resp = await client.get("/api/eval/corrections/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/eval/corrections/{dedup_hash}
# ---------------------------------------------------------------------------


async def test_delete_eval_correction(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    cur = _make_cursor()
    cur.rowcount = 1
    fake_conn.execute = AsyncMock(return_value=cur)
    resp = await client.delete(f"/api/eval/corrections/{FAKE_JOB_ROW['dedup_hash']}")
    assert resp.status_code == 204
    assert resp.content == b""


async def test_delete_eval_correction_not_found(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    cur = _make_cursor()
    cur.rowcount = 0
    fake_conn.execute = AsyncMock(return_value=cur)
    resp = await client.delete("/api/eval/corrections/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/eval/corrections (list)
# ---------------------------------------------------------------------------


async def test_list_eval_corrections_empty(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor())
    resp = await client.get("/api/eval/corrections")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_eval_corrections_returns_rows(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_CORRECTION_ROW))
    resp = await client.get("/api/eval/corrections")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["corrected_score"] == 2


async def test_list_eval_corrections_filtered_by_model_and_profile(
    client: AsyncClient, fake_conn: AsyncMock
) -> None:
    fake_conn.execute = AsyncMock(return_value=_make_cursor(FAKE_CORRECTION_ROW))
    resp = await client.get(
        "/api/eval/corrections?model=qwen3-coder:30b&profile_version=v3"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["original_model"] == "qwen3-coder:30b"
