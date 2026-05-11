import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = Path("config/company_boards.json")

# All board types the discovery system knows about
KNOWN_BOARDS = ("lever", "ashby", "greenhouse")


def load(path: Path = DEFAULT_PATH) -> dict[str, list[str]]:
    """Return {company_slug: [board, ...]} for all known mappings."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to load company boards from %s: %s", path, exc)
        return {}


def save(db: dict[str, list[str]], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(db, indent=2, sort_keys=True) + "\n")


def merge(db: dict[str, list[str]], discovered: dict[str, list[str]]) -> dict[str, list[str]]:
    """Merge discovered boards into db, updating existing entries."""
    merged = dict(db)
    for company, boards in discovered.items():
        merged[company] = sorted(set(merged.get(company, []) + boards))
    return merged


def boards_for(company: str, db: dict[str, list[str]]) -> list[str]:
    return db.get(company, [])
