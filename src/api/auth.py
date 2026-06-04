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

BYPASS_VAR = "AUTH_BYPASS_DEV"
_CONFIG_PATH = Path("config/auth.yml")

_allowed_emails: frozenset[str] = frozenset()


@dataclass
class Principal:
    email: str
    roles: list[str] = field(default_factory=list)
    raw_claims: dict = field(default_factory=dict)


_DEV_PRINCIPAL = Principal(email="dev@localhost", roles=["dev-bypass"])


def load_auth_config() -> list[str]:
    data = yaml.safe_load(_CONFIG_PATH.read_text())
    return [e.lower() for e in (data.get("allowed_emails") or [])]


def init(emails: list[str]) -> None:
    global _allowed_emails
    _allowed_emails = frozenset(e.lower() for e in emails)


def current_principal(request: Request) -> Principal:
    if os.environ.get(BYPASS_VAR):
        return _DEV_PRINCIPAL

    header = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not header:
        raise HTTPException(status_code=401, detail="Missing authentication")

    try:
        claims = json.loads(base64.b64decode(header))
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed authentication header")

    email = (claims.get("userDetails") or "").lower()
    roles = claims.get("userRoles") or []

    if email not in _allowed_emails:
        raise HTTPException(status_code=403, detail="Access denied")

    return Principal(email=email, roles=roles, raw_claims=claims)
