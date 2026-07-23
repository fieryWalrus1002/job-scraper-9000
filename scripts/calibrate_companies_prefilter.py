#!/usr/bin/env python3
"""Audit historical companies runs before calibrating an embedding veto.

The command reads only local pipeline-run JSONL files. It deliberately does not score,
rank, or route postings: it reports whether compatible pre-veto labels are dense enough
for a later calibration decision.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from prefilter.embedding.loaders import parse_postings_jsonl

log = logging.getLogger(__name__)

SHADOW_LABELED_MINIMUM = 300
SHADOW_GOOD_MINIMUM = 100
AUTO_SWITCH_LABELED_MINIMUM = 1000
AUTO_SWITCH_GOOD_MINIMUM = 300


@dataclass(frozen=True)
class CohortKey:
    """The provenance fields that make skills-fit labels comparable."""

    profile_version: str
    provider: str
    model: str

    def as_dict(self) -> dict[str, str]:
        return {
            "profile_version": self.profile_version,
            "provider": self.provider,
            "model": self.model,
        }


@dataclass(frozen=True)
class ScoredLabel:
    dedup_hash: str
    fit_score: int | None
    cohort: CohortKey
    scored_at: str
    scored_at_datetime: datetime


@dataclass(frozen=True)
class RunAudit:
    run_id: str
    path: Path
    raw: int
    labeled: int
    good: int
    junk: int
    failures: int
    coverage: float | None
    labels: tuple[ScoredLabel, ...]


def _context(path: Path, line_number: int) -> str:
    return f"Malformed skills-fit input {path} line {line_number}"


def _require_non_empty_string(value: object, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{context}: required field {field!r} must be a non-empty string"
        )
    return value.strip()


def _parse_scored_at(value: str, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context}: metadata.scored_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context}: metadata.scored_at must include a timezone")
    return parsed


def parse_scored_labels_jsonl(text: str, path: Path) -> dict[str, ScoredLabel]:
    """Parse labels plus their metadata provenance with path and line context.

    ``parse_skills_fit_jsonl`` is intentionally not used here: its public return
    value drops provenance and it rejects the persisted ``fit_score: null`` failure
    shape that this audit must count. This parser retains those two required facts.
    """
    labels: dict[str, ScoredLabel] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        context = _context(path, line_number)
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{context}: invalid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{context}: expected a JSON object")

        dedup_hash = _require_non_empty_string(
            record.get("dedup_hash"), "dedup_hash", context
        )
        if dedup_hash in labels:
            raise ValueError(f"{context}: duplicate dedup_hash {dedup_hash!r}")

        if "ai_fit" not in record:
            raise ValueError(f"{context}: required field 'ai_fit' is missing")
        ai_fit = record["ai_fit"]
        if ai_fit is None:
            fit_score: int | None = None
        elif not isinstance(ai_fit, dict):
            raise ValueError(f"{context}: ai_fit must be an object or null")
        else:
            if "fit_score" not in ai_fit:
                raise ValueError(
                    f"{context}: required field 'ai_fit.fit_score' is missing"
                )
            value = ai_fit["fit_score"]
            if value is None:
                fit_score = None
            elif isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"{context}: ai_fit.fit_score must be an integer or null"
                )
            elif not 1 <= value <= 5:
                raise ValueError(f"{context}: ai_fit.fit_score must be in 1..5")
            else:
                fit_score = value

        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"{context}: metadata must be an object")
        cohort = CohortKey(
            profile_version=_require_non_empty_string(
                metadata.get("profile_version"), "metadata.profile_version", context
            ),
            provider=_require_non_empty_string(
                metadata.get("provider"), "metadata.provider", context
            ),
            model=_require_non_empty_string(
                metadata.get("model"), "metadata.model", context
            ),
        )
        scored_at = _require_non_empty_string(
            metadata.get("scored_at"), "metadata.scored_at", context
        )
        labels[dedup_hash] = ScoredLabel(
            dedup_hash=dedup_hash,
            fit_score=fit_score,
            cohort=cohort,
            scored_at=scored_at,
            scored_at_datetime=_parse_scored_at(scored_at, context),
        )
    return labels


def discover_run_dirs(runs_root: Path, user_slug: str) -> list[Path]:
    """Return complete user run directories, logging incomplete runs loudly."""
    if not runs_root.is_dir():
        raise FileNotFoundError(
            f"Runs root does not exist or is not a directory: {runs_root}"
        )

    run_dirs: list[Path] = []
    for run_root in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        user_dir = run_root / user_slug
        companies_path = user_dir / "scrape" / "companies.jsonl"
        scored_path = user_dir / "skills_fit" / "scored.jsonl"
        missing = [
            str(path.relative_to(user_dir))
            for path in (companies_path, scored_path)
            if not path.is_file()
        ]
        if missing:
            log.warning(
                "Skipping run %s: missing %s", run_root.name, ", ".join(missing)
            )
            continue
        run_dirs.append(user_dir)
    return run_dirs


def audit_run(run_dir: Path) -> RunAudit:
    """Join one raw companies pool to its scored labels by ``dedup_hash``."""
    companies_path = run_dir / "scrape" / "companies.jsonl"
    scored_path = run_dir / "skills_fit" / "scored.jsonl"
    postings = parse_postings_jsonl(
        companies_path.read_text(encoding="utf-8"), companies_path
    )
    labels_by_hash = parse_scored_labels_jsonl(
        scored_path.read_text(encoding="utf-8"), scored_path
    )

    matched_labels = tuple(
        labels_by_hash[posting.dedup_hash]
        for posting in postings
        if posting.dedup_hash in labels_by_hash
    )
    good = sum(
        label.fit_score is not None and label.fit_score >= 4 for label in matched_labels
    )
    junk = sum(
        label.fit_score is not None and label.fit_score <= 2 for label in matched_labels
    )
    failures = sum(label.fit_score is None for label in matched_labels)
    raw = len(postings)
    labeled = len(matched_labels)
    return RunAudit(
        run_id=run_dir.parent.name,
        path=run_dir,
        raw=raw,
        labeled=labeled,
        good=good,
        junk=junk,
        failures=failures,
        coverage=labeled / raw if raw else None,
        labels=matched_labels,
    )


def _cohort_summary(
    cohort: CohortKey, labels: Iterable[tuple[str, ScoredLabel]]
) -> dict[str, object]:
    labels_list = list(labels)
    scores = [label.fit_score for _, label in labels_list]
    timestamps = [
        (label.scored_at_datetime, label.scored_at) for _, label in labels_list
    ]
    run_ids = {run_id for run_id, _ in labels_list}
    earliest_datetime, earliest = min(timestamps)
    latest_datetime, latest = max(timestamps)
    return {
        **cohort.as_dict(),
        "labeled": len(labels_list),
        "good": sum(score is not None and score >= 4 for score in scores),
        "junk": sum(score is not None and score <= 2 for score in scores),
        "failures": sum(score is None for score in scores),
        "distinct_run_count": len(run_ids),
        "min_scored_at": earliest,
        "max_scored_at": latest,
        "holdout_feasible": len(run_ids) >= 2 and earliest_datetime < latest_datetime,
    }


def eligibility_verdict(labeled: int, good: int) -> dict[str, object]:
    """Apply the spec's label-density thresholds to one compatible cohort."""
    shadow_eligible = labeled >= SHADOW_LABELED_MINIMUM and good >= SHADOW_GOOD_MINIMUM
    auto_switch_candidate = (
        labeled >= AUTO_SWITCH_LABELED_MINIMUM and good >= AUTO_SWITCH_GOOD_MINIMUM
    )
    if auto_switch_candidate:
        verdict = "auto_switch_candidate"
    elif shadow_eligible:
        verdict = "shadow_eligible"
    else:
        verdict = "insufficient"
    return {
        "verdict": verdict,
        "shadow_eligible": shadow_eligible,
        "auto_switch_candidate": auto_switch_candidate,
        "shortfall": {
            "shadow_labeled": max(0, SHADOW_LABELED_MINIMUM - labeled),
            "shadow_good": max(0, SHADOW_GOOD_MINIMUM - good),
            "auto_switch_labeled": max(0, AUTO_SWITCH_LABELED_MINIMUM - labeled),
            "auto_switch_good": max(0, AUTO_SWITCH_GOOD_MINIMUM - good),
        },
    }


def audit_user_runs(runs_root: Path, user_slug: str) -> dict[str, object]:
    """Audit all complete runs for one user and return a JSON-serializable report."""
    audits = [audit_run(run_dir) for run_dir in discover_run_dirs(runs_root, user_slug)]
    grouped: defaultdict[CohortKey, list[tuple[str, ScoredLabel]]] = defaultdict(list)
    for audit in audits:
        for label in audit.labels:
            grouped[label.cohort].append((audit.run_id, label))
    cohorts = [
        _cohort_summary(cohort, labels)
        for cohort, labels in sorted(
            grouped.items(),
            key=lambda item: (item[0].profile_version, item[0].provider, item[0].model),
        )
    ]
    largest_cohort = max(
        cohorts,
        key=lambda cohort: (
            int(cohort["labeled"]),
            str(cohort["profile_version"]),
            str(cohort["provider"]),
            str(cohort["model"]),
        ),
        default=None,
    )
    total_raw = sum(audit.raw for audit in audits)
    total_labeled = sum(audit.labeled for audit in audits)
    total_good = sum(audit.good for audit in audits)
    total_junk = sum(audit.junk for audit in audits)
    total_failures = sum(audit.failures for audit in audits)
    eligibility = eligibility_verdict(
        int(largest_cohort["labeled"]) if largest_cohort else 0,
        int(largest_cohort["good"]) if largest_cohort else 0,
    )
    eligibility["cohort"] = (
        {key: largest_cohort[key] for key in ("profile_version", "provider", "model")}
        if largest_cohort
        else None
    )
    return {
        "user_slug": user_slug,
        "runs": [
            {
                "run_id": audit.run_id,
                "path": str(audit.path),
                "raw": audit.raw,
                "labeled": audit.labeled,
                "good": audit.good,
                "junk": audit.junk,
                "failures": audit.failures,
                "selection_bias_coverage": audit.coverage,
            }
            for audit in audits
        ],
        "totals": {
            "raw": total_raw,
            "labeled": total_labeled,
            "good": total_good,
            "junk": total_junk,
            "failures": total_failures,
            "selection_bias_coverage": total_labeled / total_raw if total_raw else None,
        },
        "cohorts": cohorts,
        "eligibility": eligibility,
    }


def format_summary(report: dict[str, object]) -> str:
    """Render a concise human-readable view alongside the JSON artifact."""
    runs = report["runs"]
    cohorts = report["cohorts"]
    totals = report["totals"]
    eligibility = report["eligibility"]
    assert isinstance(runs, list)
    assert isinstance(cohorts, list)
    assert isinstance(totals, dict)
    assert isinstance(eligibility, dict)

    lines = [
        "Companies prefilter calibration audit",
        "",
        "Per-run selection-bias coverage:",
    ]
    lines.append("run_id\traw\tlabeled\tgood\tjunk\tfailures\tcoverage")
    for run in runs:
        assert isinstance(run, dict)
        coverage = run["selection_bias_coverage"]
        coverage_text = "n/a" if coverage is None else f"{float(coverage):.1%}"
        lines.append(
            f"{run['run_id']}\t{run['raw']}\t{run['labeled']}\t{run['good']}\t"
            f"{run['junk']}\t{run['failures']}\t{coverage_text}"
        )
    total_coverage = totals["selection_bias_coverage"]
    total_coverage_text = (
        "n/a" if total_coverage is None else f"{float(total_coverage):.1%}"
    )
    lines.append(
        f"TOTAL\t{totals['raw']}\t{totals['labeled']}\t{totals['good']}\t"
        f"{totals['junk']}\t{totals['failures']}\t{total_coverage_text}"
    )
    lines.extend(["", "Compatible cohorts:"])
    lines.append(
        "profile_version\tprovider\tmodel\tlabeled\tgood\tjunk\truns\tmin_scored_at\tmax_scored_at\tholdout_feasible"
    )
    for cohort in cohorts:
        assert isinstance(cohort, dict)
        lines.append(
            f"{cohort['profile_version']}\t{cohort['provider']}\t{cohort['model']}\t"
            f"{cohort['labeled']}\t{cohort['good']}\t{cohort['junk']}\t"
            f"{cohort['distinct_run_count']}\t{cohort['min_scored_at']}\t"
            f"{cohort['max_scored_at']}\t{cohort['holdout_feasible']}"
        )
    cohort = eligibility["cohort"]
    cohort_text = (
        "none" if cohort is None else "/".join(str(value) for value in cohort.values())
    )
    shortfall = eligibility["shortfall"]
    assert isinstance(shortfall, dict)
    lines.extend(
        [
            "",
            f"Verdict ({cohort_text}): {eligibility['verdict']}",
            "Shortfall: "
            f"shadow labeled={shortfall['shadow_labeled']}, shadow good={shortfall['shadow_good']}; "
            f"auto-switch labeled={shortfall['auto_switch_labeled']}, auto-switch good={shortfall['auto_switch_good']}",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-slug", required=True)
    parser.add_argument("--runs-root", type=Path, default=Path("data/pipeline_runs"))
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    report = audit_user_runs(args.runs_root, args.user_slug)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(format_summary(report))
    return report


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
