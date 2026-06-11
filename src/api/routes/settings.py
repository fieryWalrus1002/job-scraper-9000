"""Per-user settings: candidate profile + search config / policies (Phase 12).

Reads/writes the two config tables (migration 0009) scoped to the current
user. The DB stores the human-facing format (what the form edits); the
human→pipeline transform stays in the admin pull script, not here.

- profile_version is recomputed server-side on every profile save (content
  hash, shared helper) — never client-supplied (spec §2).
- policies are derived from the search config server-side, mirroring
  scripts/push_user_config.py so there's one derivation path, no drift.
- No admin cross-user surface (admin uses the scripts); no pipeline trigger
  (spec decision 4). Profile content never goes to logs (spec §1.8).

Validation is FastAPI-automatic: the PUT bodies are the shared Pydantic
models (extra="forbid"), so a typo'd key or bad type returns 422 with
field-level errors — exactly what the form needs to render inline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter
from psycopg.types.json import Json
from pydantic import BaseModel

from user_config import (
    CandidateProfileInput,
    SearchConfigInput,
    compute_profile_version,
    derive_policies,
)

from ..dependencies import CurrentUser, Pool

router = APIRouter(prefix="/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    """Both payloads + versioning. Null payloads = not yet configured, which
    the frontend renders as the onboarding state."""

    profile: dict | None = None
    profile_version: str | None = None
    profile_updated_at: datetime | None = None
    search: dict | None = None
    policies: dict | None = None
    search_updated_at: datetime | None = None


class ProfileSaveResponse(BaseModel):
    profile_version: str
    updated_at: datetime


class SearchSaveResponse(BaseModel):
    # Echo the derived policies so the form can show the effective gates.
    policies: dict
    updated_at: datetime


@router.get("", response_model=SettingsResponse)
async def get_settings(pool: Pool, user: CurrentUser) -> SettingsResponse:
    async with pool.connection() as conn:
        prof = await (
            await conn.execute(
                "SELECT payload, profile_version, updated_at "
                "FROM app.candidate_profiles WHERE user_id = %(uid)s",
                {"uid": user.id},
            )
        ).fetchone()
        srch = await (
            await conn.execute(
                "SELECT payload, policies, updated_at "
                "FROM app.user_search_configs WHERE user_id = %(uid)s",
                {"uid": user.id},
            )
        ).fetchone()

    prof = cast("dict[str, Any] | None", prof)
    srch = cast("dict[str, Any] | None", srch)
    return SettingsResponse(
        profile=prof["payload"] if prof else None,
        profile_version=prof["profile_version"] if prof else None,
        profile_updated_at=prof["updated_at"] if prof else None,
        search=srch["payload"] if srch else None,
        policies=srch["policies"] if srch else None,
        search_updated_at=srch["updated_at"] if srch else None,
    )


@router.put("/profile", response_model=ProfileSaveResponse)
async def put_profile(
    body: CandidateProfileInput, pool: Pool, user: CurrentUser
) -> ProfileSaveResponse:
    # Store the human format; profile_version is the authoritative content hash.
    payload = body.model_dump(mode="json")
    version = compute_profile_version(payload)
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                INSERT INTO app.candidate_profiles (user_id, payload, profile_version)
                VALUES (%(uid)s, %(payload)s, %(version)s)
                ON CONFLICT (user_id) DO UPDATE
                SET payload = EXCLUDED.payload,
                    profile_version = EXCLUDED.profile_version,
                    updated_at = now()
                RETURNING profile_version, updated_at
                """,
                {"uid": user.id, "payload": Json(payload), "version": version},
            )
        ).fetchone()
    row = cast(dict[str, Any], row)
    return ProfileSaveResponse(
        profile_version=row["profile_version"], updated_at=row["updated_at"]
    )


@router.put("/search", response_model=SearchSaveResponse)
async def put_search(
    body: SearchConfigInput, pool: Pool, user: CurrentUser
) -> SearchSaveResponse:
    payload = body.model_dump(mode="json")
    policies = derive_policies(body).model_dump(mode="json")
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                INSERT INTO app.user_search_configs (user_id, payload, policies)
                VALUES (%(uid)s, %(payload)s, %(policies)s)
                ON CONFLICT (user_id) DO UPDATE
                SET payload = EXCLUDED.payload,
                    policies = EXCLUDED.policies,
                    updated_at = now()
                RETURNING policies, updated_at
                """,
                {"uid": user.id, "payload": Json(payload), "policies": Json(policies)},
            )
        ).fetchone()
    row = cast(dict[str, Any], row)
    return SearchSaveResponse(policies=row["policies"], updated_at=row["updated_at"])
