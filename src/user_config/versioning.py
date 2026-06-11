"""Content-hash ``profile_version`` (specs/configs_in_db_design.md §2).

The hand-bumped version string doesn't survive non-admins editing profiles in
a UI, so the version becomes a deterministic content hash computed on every
save. Shared here so the push script and the API settings endpoint (#181)
compute it identically — a second implementation would drift.

Format: ``YYYY-MM-DD.<sha256[:12]>`` over the canonical JSON serialization of
the payload. Date prefix for humans, hash for machines. Both halves are opaque
text to every downstream consumer (scores/eval tables treat it as a label).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date


def canonical_json(payload: dict) -> str:
    """Stable serialization for hashing: sorted keys, no incidental whitespace.

    Two payloads that differ only in key order or formatting hash identically —
    the hash tracks *content*, not serialization.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_profile_version(payload: dict, *, today: date | None = None) -> str:
    """``YYYY-MM-DD.<sha256[:12]>`` for a profile payload (spec §2).

    ``today`` is injectable for deterministic tests; defaults to the local
    date, matching when the save actually happens.
    """
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:12]
    return f"{(today or date.today()).isoformat()}.{digest}"
