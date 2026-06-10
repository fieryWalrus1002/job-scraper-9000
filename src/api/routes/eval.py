# app/routes/eval.py
from typing import Annotated, Any, cast
from fastapi import APIRouter, HTTPException, Query, Response

from ..dependencies import Pool, Auth
from ..schemas import EvalCorrectionIn, EvalCorrectionOut

router = APIRouter(prefix="/eval", tags=["Eval Corrections"])

# ---------------------------------------------------------------------------
# Eval corrections — dashboard-sourced gold set for skills_fit
# ---------------------------------------------------------------------------

_CORRECTION_COLS = """
    dedup_hash, corrected_score, correction_reason,
    original_score, original_model, profile_version, corrected_at
"""


@router.post("/corrections", response_model=EvalCorrectionOut, status_code=201)
async def upsert_eval_correction(body: EvalCorrectionIn, pool: Pool, principal: Auth):
    """Upsert a human correction to a job's skills_fit score.

    The server snapshots the current AI score/model/profile_version from
    raw.scored_job_postings so the correction stays meaningful even after a
    later re-scoring run with different (model, profile_version). Last-write-
    wins on dedup_hash.
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT fit_score, model, profile_version
            FROM raw.scored_job_postings
            WHERE dedup_hash = %(dedup_hash)s
            """,
            {"dedup_hash": body.dedup_hash},
        )
        job_row = await cur.fetchone()
        if job_row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job_row = cast(dict[str, Any], job_row)

        cur = await conn.execute(
            f"""
            INSERT INTO app.eval_corrections
                (dedup_hash, corrected_score, correction_reason,
                 original_score, original_model, profile_version)
            VALUES
                (%(dedup_hash)s, %(corrected_score)s, %(correction_reason)s,
                 %(original_score)s, %(original_model)s, %(profile_version)s)
            ON CONFLICT (dedup_hash) DO UPDATE
                SET corrected_score   = EXCLUDED.corrected_score,
                    correction_reason = EXCLUDED.correction_reason,
                    original_score    = EXCLUDED.original_score,
                    original_model    = EXCLUDED.original_model,
                    profile_version   = EXCLUDED.profile_version,
                    corrected_at      = now()
            RETURNING {_CORRECTION_COLS}
            """,
            {
                "dedup_hash": body.dedup_hash,
                "corrected_score": body.corrected_score,
                "correction_reason": body.correction_reason,
                "original_score": job_row["fit_score"],
                "original_model": job_row["model"],
                "profile_version": job_row["profile_version"],
            },
        )
        row = await cur.fetchone()
    return EvalCorrectionOut.model_validate(row)


@router.get("/corrections/{dedup_hash}", response_model=EvalCorrectionOut)
async def get_eval_correction(dedup_hash: str, pool: Pool, principal: Auth):
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"""
            SELECT {_CORRECTION_COLS}
            FROM app.eval_corrections
            WHERE dedup_hash = %(dedup_hash)s
            """,
            {"dedup_hash": dedup_hash},
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Correction not found")
    return EvalCorrectionOut.model_validate(row)


@router.delete("/corrections/{dedup_hash}", status_code=204, response_class=Response)
async def delete_eval_correction(dedup_hash: str, pool: Pool, principal: Auth):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM app.eval_corrections WHERE dedup_hash = %(dedup_hash)s",
            {"dedup_hash": dedup_hash},
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Correction not found")
    return Response(status_code=204)


@router.get("/corrections", response_model=list[EvalCorrectionOut])
async def list_eval_corrections(
    pool: Pool,
    principal: Auth,
    model: Annotated[str | None, Query(max_length=200)] = None,
    profile_version: Annotated[str | None, Query(max_length=100)] = None,
):
    filters: list[str] = []
    params: dict = {}
    if model is not None:
        filters.append("original_model = %(model)s")
        params["model"] = model
    if profile_version is not None:
        filters.append("profile_version = %(profile_version)s")
        params["profile_version"] = profile_version
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = f"""
        SELECT {_CORRECTION_COLS}
        FROM app.eval_corrections
        {where}
        ORDER BY corrected_at DESC
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)  # type: ignore[arg-type]
        rows = await cur.fetchall()
    return [EvalCorrectionOut.model_validate(r) for r in rows]
