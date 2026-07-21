"""Remote-filter bake-off helpers for quality × cost comparison."""

from typing import Any

from agent_eval.run_compare import SCORER_REGISTRY, format_cell

BAKEOFF_COLUMNS = [
    "champion",
    "run_id",
    "model",
    "micro_acc",
    "remote_recall",
    "remote_fn",
    "remote_fp",
    "macro_f1",
    "skipped_failed",
    "est_cost",
    "cost_per_correct",
]


def ensure_bakeoff_comparable(runs: list[dict[str, Any]]) -> None:
    """Fail if selected bake-off runs do not share required provenance hashes."""
    for field in ("gold_hash", "prompt_hash"):
        missing = [run.get("run_id", "") for run in runs if not run.get(field)]
        if missing:
            raise ValueError(
                f"--bakeoff requires {field} on every selected run; "
                f"missing for: {', '.join(missing)}"
            )
        values = {run[field] for run in runs}
        if len(values) > 1:
            raise ValueError(
                f"--bakeoff selected runs with mixed {field}; not comparable"
            )


def sort_bakeoff_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return bake-off rows sorted by cost per correct, then quality guardrails."""
    return sorted(
        rows,
        key=lambda r: (
            r.get("cost_per_correct") is None,
            r.get("cost_per_correct") if r.get("cost_per_correct") is not None else 0,
            -(r.get("remote_recall") or 0),
            -(r.get("micro_acc") or 0),
        ),
    )


def format_money(value: Any) -> str:
    """Format a nullable USD value for bake-off table display."""
    if value is None:
        return "—"
    return f"${value:.6f}"


def build_bakeoff_render_rows(
    rows: list[dict[str, Any]], champion_run_id: str | None
) -> list[dict[str, str]]:
    """Build formatted, print-ready remote-filter bake-off table rows."""
    spec = SCORER_REGISTRY["remote_filter_categorical"]
    rendered_rows = []
    for row in sort_bakeoff_rows(rows):
        rendered_rows.append(
            {
                "champion": "*" if row.get("run_id") == champion_run_id else "",
                "run_id": str(row.get("run_id", "")),
                "model": str(row.get("model", "")),
                "micro_acc": format_cell("micro_acc", row.get("micro_acc"), spec),
                "remote_recall": format_cell(
                    "remote_recall", row.get("remote_recall"), spec
                ),
                "remote_fn": format_cell("remote_fn", row.get("remote_fn"), spec),
                "remote_fp": format_cell("remote_fp", row.get("remote_fp"), spec),
                "macro_f1": format_cell("macro_f1", row.get("macro_f1"), spec),
                "skipped_failed": str(row.get("skipped_failed", "")),
                "est_cost": format_money(row.get("est_cost")),
                "cost_per_correct": format_money(row.get("cost_per_correct")),
            }
        )
    return rendered_rows
