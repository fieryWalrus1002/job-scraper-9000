from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

BYPASS_VAR = "AUTH_BYPASS"
_CONFIG_PATH = Path("config/auth.yml")

ROLES = frozenset({"admin", "member"})

# Entra forwards the object id either as the short or the full URI claim type,
# depending on the token shape SWA was handed.
_OID_CLAIM_TYPES = frozenset(
    {"http://schemas.microsoft.com/identity/claims/objectidentifier", "oid"}
)

_allowed_emails: frozenset[str] = frozenset()

# One-time INFO log of which claim keys arrive on the first authenticated
# request (#165 verification step: does SWA forward the Entra oid?). Keys
# only — never claim values.
_claim_keys_logged = False


@dataclass(frozen=True)
class AuthUser:
    """One allowlist entry from config/auth.yml."""

    email: str
    role: str


@dataclass
class Principal:
    email: str
    roles: list[str] = field(default_factory=list)
    external_id: str | None = None
    identity_provider: str | None = None
    raw_claims: dict = field(default_factory=dict)


_DEV_PRINCIPAL = Principal(
    email="dev@localhost",
    roles=["dev-bypass"],
    external_id="dev-bypass",
    identity_provider="dev",
)


def load_auth_config() -> list[AuthUser]:
    if not _CONFIG_PATH.exists():
        raise RuntimeError(f"Auth config not found: {_CONFIG_PATH}")
    data = yaml.safe_load(_CONFIG_PATH.read_text())
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Auth config must be a YAML mapping, got: {type(data).__name__}"
        )
    if "allowed_emails" in data and "users" not in data:
        raise RuntimeError(
            "Auth config uses the legacy 'allowed_emails' format. "
            "Migrate to the 'users' list (email + role) — see config/auth.yml.example."
        )
    raw = data.get("users")
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("Auth config must contain a non-empty 'users' list")

    users: list[AuthUser] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise RuntimeError(f"users[{i}] must be a mapping, got: {entry!r}")
        email = entry.get("email")
        if not isinstance(email, str) or not email.strip():
            raise RuntimeError(f"users[{i}] is missing a non-empty 'email'")
        role = entry.get("role", "member")
        if role not in ROLES:
            raise RuntimeError(
                f"users[{i}] has invalid role {role!r}; must be one of {sorted(ROLES)}"
            )
        users.append(AuthUser(email=email.strip().lower(), role=role))

    emails = [u.email for u in users]
    if len(set(emails)) != len(emails):
        raise RuntimeError("Auth config contains duplicate emails")
    return users


def init(users: list[AuthUser]) -> None:
    global _allowed_emails
    _allowed_emails = frozenset(u.email.lower() for u in users)


def _extract_external_id(claims: dict) -> str | None:
    """Stable subject id: Entra oid when forwarded, else SWA's userId.

    Email is never a fallback — it rotates, and app.users joins on this value.
    """
    for c in claims.get("claims") or []:
        if isinstance(c, dict) and c.get("typ") in _OID_CLAIM_TYPES and c.get("val"):
            return str(c["val"])
    user_id = claims.get("userId")
    if isinstance(user_id, str) and user_id.strip():
        return user_id
    return None


def _log_claim_keys_once(claims: dict) -> None:
    global _claim_keys_logged
    if _claim_keys_logged:
        return
    _claim_keys_logged = True
    typs = sorted(
        {
            str(c.get("typ"))
            for c in claims.get("claims") or []
            if isinstance(c, dict) and c.get("typ")
        }
    )
    log.info(
        "First authenticated request: principal keys=%s, claim typs=%s",
        sorted(claims.keys()),
        typs,
    )


def current_principal(request: Request) -> Principal:
    if os.environ.get(BYPASS_VAR) == "1":
        return _DEV_PRINCIPAL

    header = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not header:
        raise HTTPException(status_code=401, detail="Missing authentication")

    try:
        claims = json.loads(base64.b64decode(header, validate=True))
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed authentication header")

    if not isinstance(claims, dict):
        raise HTTPException(status_code=401, detail="Malformed authentication header")

    user_details = claims.get("userDetails")
    if not isinstance(user_details, str):
        raise HTTPException(status_code=401, detail="Malformed authentication header")
    email = user_details.lower()

    user_roles = claims.get("userRoles") or []
    if not isinstance(user_roles, list):
        raise HTTPException(status_code=401, detail="Malformed authentication header")
    roles = [r for r in user_roles if isinstance(r, str)]

    if email not in _allowed_emails:
        raise HTTPException(status_code=403, detail="Access denied")

    _log_claim_keys_once(claims)

    identity_provider = claims.get("identityProvider")
    return Principal(
        email=email,
        roles=roles,
        external_id=_extract_external_id(claims),
        identity_provider=identity_provider
        if isinstance(identity_provider, str)
        else None,
        raw_claims=claims,
    )
