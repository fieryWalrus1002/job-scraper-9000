#!/usr/bin/env python3
"""Export the FastAPI app's OpenAPI schema to a JSON file.

Usage:
    uv run scripts/export_openapi.py                      # writes frontend/openapi.json
    uv run scripts/export_openapi.py --out path/to/out.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "frontend" / "openapi.json"),
        metavar="PATH",
    )
    args = parser.parse_args()

    from api.main import app  # noqa: E402 — deferred so sys.path is set first

    schema = app.openapi()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI schema to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
