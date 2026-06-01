#!/usr/bin/env python3
"""View ranked skills-fit results from a scored JSONL file."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, TextIO

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


TABLE_HEADERS = ("RANK", "SCORE", "BLOCKERS", "TITLE", "COMPANY", "LOCATION")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", help="Partition date in YYYY-MM-DD form")
    parser.add_argument("--input", help="Override scored input JSONL path")
    parser.add_argument("--limit", type=int, help="Maximum number of rows to display")
    parser.add_argument(
        "--show-rationale",
        action="store_true",
        help="Print rationale and hard concerns for displayed rows",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    return args


def resolve_input_path(*, run_date: str | None, input_path: str | Path | None) -> Path:
    if input_path is not None:
        return Path(input_path)
    if run_date:
        return Path("data/scored") / run_date / "skills_fit_scored.jsonl"
    raise ValueError("--run-date or --input is required")


def read_scored_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(
                    "Skipping malformed JSONL line %d in %s: %s", line_number, path, exc
                )
                continue
            if not isinstance(value, dict):
                log.warning(
                    "Skipping non-object JSONL line %d in %s", line_number, path
                )
                continue
            rows.append(value)
    return rows


def _display_text(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _display_score(value: Any) -> str:
    return "-" if value is None else str(value)


def _ai_fit_dict(row: dict[str, Any]) -> dict[str, Any]:
    val = row.get("ai_fit")
    return val if isinstance(val, dict) else {}


def _hard_concerns(row: dict[str, Any]) -> list[str]:
    value = _ai_fit_dict(row).get("hard_concerns")
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def format_table_row(rank: int, row: dict[str, Any]) -> str:
    blockers = "BLOCKERS" if _hard_concerns(row) else ""
    columns = (
        str(rank),
        _display_score(_ai_fit_dict(row).get("fit_score")),
        blockers,
        _truncate(_display_text(row.get("title")), 40),
        _truncate(_display_text(row.get("company")), 24),
        _truncate(_display_text(row.get("location")), 24),
    )
    return f"{columns[0]:>4}  {columns[1]:>5}  {columns[2]:<8}  {columns[3]:<40}  {columns[4]:<24}  {columns[5]:<24}"


def render_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int | None = None,
    show_rationale: bool = False,
    out: TextIO = sys.stdout,
) -> int:
    displayed = rows[:limit] if limit is not None else rows
    if not displayed:
        return 0

    header = f"{TABLE_HEADERS[0]:>4}  {TABLE_HEADERS[1]:>5}  {TABLE_HEADERS[2]:<8}  {TABLE_HEADERS[3]:<40}  {TABLE_HEADERS[4]:<24}  {TABLE_HEADERS[5]:<24}"
    print(header, file=out)
    print("-" * len(header), file=out)

    for rank, row in enumerate(displayed, start=1):
        print(format_table_row(rank, row), file=out)
        if show_rationale:
            concerns = _hard_concerns(row)
            rationale = _display_text(_ai_fit_dict(row).get("score_rationale"))
            concerns_text = "; ".join(concerns) if concerns else "-"
            print(f"      rationale: {rationale}", file=out)
            print(f"      hard concerns: {concerns_text}", file=out)
            print(file=out)
    return len(displayed)


def view_results(
    *,
    run_date: str | None = None,
    input_path: str | Path | None = None,
    limit: int | None = None,
    show_rationale: bool = False,
    out: TextIO = sys.stdout,
) -> dict[str, Any]:
    path = resolve_input_path(run_date=run_date, input_path=input_path)
    if not path.exists():
        raise FileNotFoundError(f"Scored input file not found: {path}")

    rows = read_scored_rows(path)
    if not rows:
        log.warning("No scored rows found in %s", path)
        return {"input_path": str(path), "row_count": 0, "displayed_count": 0}

    displayed_count = render_rows(
        rows,
        limit=limit,
        show_rationale=show_rationale,
        out=out,
    )
    return {
        "input_path": str(path),
        "row_count": len(rows),
        "displayed_count": displayed_count,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        view_results(
            run_date=args.run_date,
            input_path=args.input,
            limit=args.limit,
            show_rationale=args.show_rationale,
        )
    except (FileNotFoundError, ValueError) as exc:
        log.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
