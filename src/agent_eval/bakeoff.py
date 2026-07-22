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
    "weighted_error",
    "skipped_failed",
    "est_cost",
    "cost_per_correct",
]

# Bake-off ranking keys. `cost_per_correct` is the default decision axis (spec
# §Decision metric); `weighted_error` is the additive cost-asymmetry lens (#545).
RANK_KEYS = ("cost_per_correct", "weighted_error")


def ensure_bakeoff_comparable(runs: list[dict[str, Any]]) -> None:
    """Fail if selected bake-off runs do not share required provenance hashes.

    Beyond gold + system prompt, runs must share the *resolved user messages* the
    LLM actually saw: search context and ``USER_TIMEZONE`` are folded into each
    user message, so two runs can share ``gold_hash``/``prompt_hash`` yet have
    scored different inputs. Comparing them on quality × cost would be misleading.
    """
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

    # resolved_user_message_hashes is a nested provenance block: {aggregate, count}.
    # Legacy runs predating it lack the block — fail with a clear message rather
    # than silently comparing across differing inputs.
    legacy = [
        run.get("run_id", "")
        for run in runs
        if not isinstance(run.get("resolved_user_message_hashes"), dict)
    ]
    if legacy:
        raise ValueError(
            "--bakeoff requires resolved_user_message_hashes on every selected "
            f"run; missing for: {', '.join(legacy)} (legacy runs predate this "
            "provenance — re-run them to include in a bake-off)"
        )
    for key in ("aggregate", "count"):
        values = {run["resolved_user_message_hashes"].get(key) for run in runs}
        if len(values) > 1:
            raise ValueError(
                f"--bakeoff selected runs with mixed resolved_user_message_hashes "
                f"{key}; they scored different inputs and are not comparable"
            )


def sort_bakeoff_rows(
    rows: list[dict[str, Any]], rank_by: str = "cost_per_correct"
) -> list[dict[str, Any]]:
    """Return bake-off rows sorted by the ranking key, then quality guardrails.

    ``rank_by`` defaults to ``cost_per_correct`` (the spec decision axis). Passing
    ``weighted_error`` ranks by the cost-asymmetry lens instead (#545); both keys
    are ascending (lower is better), nulls sort last, and ``remote_recall`` /
    ``micro_acc`` break ties so the recall guardrail still shows through.
    """
    if rank_by not in RANK_KEYS:
        raise ValueError(f"rank_by must be one of {RANK_KEYS}; got {rank_by!r}")
    return sorted(
        rows,
        key=lambda r: (
            r.get(rank_by) is None,
            r.get(rank_by) if r.get(rank_by) is not None else 0,
            -(r.get("remote_recall") or 0),
            -(r.get("micro_acc") or 0),
        ),
    )


def format_money(value: Any) -> str:
    """Format a nullable USD value for bake-off table display."""
    if value is None:
        return "—"
    return f"${value:.6f}"


def format_weighted_error(value: Any) -> str:
    """Format a nullable weighted_error scalar for bake-off table display."""
    if value is None:
        return "—"
    return f"{value:.2f}"


def build_bakeoff_render_rows(
    rows: list[dict[str, Any]],
    champion_run_id: str | None,
    rank_by: str = "cost_per_correct",
) -> list[dict[str, str]]:
    """Build formatted, print-ready remote-filter bake-off table rows."""
    spec = SCORER_REGISTRY["remote_filter_categorical"]
    rendered_rows = []
    for row in sort_bakeoff_rows(rows, rank_by):
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
                "weighted_error": format_weighted_error(row.get("weighted_error")),
                "skipped_failed": str(row.get("skipped_failed", "")),
                "est_cost": format_money(row.get("est_cost")),
                "cost_per_correct": format_money(row.get("cost_per_correct")),
            }
        )
    return rendered_rows
