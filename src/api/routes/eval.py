# app/routes/eval.py
from typing import Annotated, Any, cast
from fastapi import APIRouter, HTTPException, Query, Response

from ..dependencies import Pool, CurrentUser
from ..schemas import EvalCorrectionIn, EvalCorrectionOut

router = APIRouter(prefix="/eval", tags=["Eval Corrections"])

# ---------------------------------------------------------------------------
# Eval corrections — per-user gold set for skills_fit
#
# Scores are per-user, so corrections are too: a user correcting their own
# score is gold data for *their* profile. Keyed (user_id, dedup_hash); all
# routes operate on the current user's rows only.
# ---------------------------------------------------------------------------

_CORRECTION_COLS = """
    dedup_hash, corrected_score, correction_reason,
    original_score, original_model, profile_version, corrected_at
"""


@router.post("/corrections", response_model=EvalCorrectionOut, status_code=201)
async def upsert_eval_correction(body: EvalCorrectionIn, pool: Pool, user: CurrentUser):
    """Upsert the current user's correction to their skills_fit score.

    The server snapshots the user's own score/model/profile_version from
    raw.job_scores so the correction stays meaningful even after a later
    re-scoring run with different (model, profile_version). Last-write-wins
    per (user, job).
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT fit_score, model, profile_version
            FROM raw.job_scores
            WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
            """,
            {"user_id": user.id, "dedup_hash": body.dedup_hash},
        )
        job_row = await cur.fetchone()
        if job_row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job_row = cast(dict[str, Any], job_row)

        cur = await conn.execute(
            f"""
            INSERT INTO app.eval_corrections
                (user_id, dedup_hash, corrected_score, correction_reason,
                 original_score, original_model, profile_version)
            VALUES
                (%(user_id)s, %(dedup_hash)s, %(corrected_score)s, %(correction_reason)s,
                 %(original_score)s, %(original_model)s, %(profile_version)s)
            ON CONFLICT (user_id, dedup_hash) DO UPDATE
                SET corrected_score   = EXCLUDED.corrected_score,
                    correction_reason = EXCLUDED.correction_reason,
                    original_score    = EXCLUDED.original_score,
                    original_model    = EXCLUDED.original_model,
                    profile_version   = EXCLUDED.profile_version,
                    corrected_at      = now()
            RETURNING {_CORRECTION_COLS}
            """,
            {
                "user_id": user.id,
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
async def get_eval_correction(dedup_hash: str, pool: Pool, user: CurrentUser):
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"""
            SELECT {_CORRECTION_COLS}
            FROM app.eval_corrections
            WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s
            """,
            {"user_id": user.id, "dedup_hash": dedup_hash},
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Correction not found")
    return EvalCorrectionOut.model_validate(row)


@router.delete("/corrections/{dedup_hash}", status_code=204, response_class=Response)
async def delete_eval_correction(dedup_hash: str, pool: Pool, user: CurrentUser):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM app.eval_corrections "
            "WHERE user_id = %(user_id)s AND dedup_hash = %(dedup_hash)s",
            {"user_id": user.id, "dedup_hash": dedup_hash},
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Correction not found")
    return Response(status_code=204)


@router.get("/corrections", response_model=list[EvalCorrectionOut])
async def list_eval_corrections(
    pool: Pool,
    user: CurrentUser,
    model: Annotated[str | None, Query(max_length=200)] = None,
    profile_version: Annotated[str | None, Query(max_length=100)] = None,
):
    filters: list[str] = ["user_id = %(user_id)s"]
    params: dict = {"user_id": user.id}
    if model is not None:
        filters.append("original_model = %(model)s")
        params["model"] = model
    if profile_version is not None:
        filters.append("profile_version = %(profile_version)s")
        params["profile_version"] = profile_version
    where = "WHERE " + " AND ".join(filters)
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
