#!/usr/bin/env python3
"""Audit historical companies runs before calibrating an embedding veto.

The command reads only local pipeline-run JSONL files. It deliberately does not score,
rank, or route postings: it reports whether compatible pre-veto labels are dense enough
for a later calibration decision.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml
from openai import OpenAI

from prefilter.embedding import (
    SCHEMAS_BY_PREFIX_SCHEME,
    CacheIdentity,
    Posting,
    RankedPosting,
    _cache_entry,
    apply_prefix_scheme,
    build_job_text,
    build_keywords_reference_text,
    build_per_keyword_reference_texts,
    build_reference_text,
    build_skills_reference_text,
    cache_identity,
    endpoint_identity,
    fetch_missing_embeddings,
    parse_cache_jsonl,
    pool_scores,
    rank_by_scores,
    validate_profile,
)
from prefilter.embedding.loaders import parse_postings_jsonl

log = logging.getLogger(__name__)

SHADOW_LABELED_MINIMUM = 300
SHADOW_GOOD_MINIMUM = 100
AUTO_SWITCH_LABELED_MINIMUM = 1000
AUTO_SWITCH_GOOD_MINIMUM = 300
DEFAULT_CUT_DEPTHS = tuple(range(10, 71, 5))
DEFAULT_CACHE_PATH = Path("data/cache/companies_prefilter_embeddings.jsonl")
DEFAULT_CURVE_OUTPUT_DIR = Path("data/calibration/companies_prefilter_curves")
REFERENCE_MODES = frozenset(
    {"blend", "keywords", "keyword-max", "keyword-mean", "skills-max", "exemplar"}
)


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
    labeled_postings: tuple[tuple[Posting, ScoredLabel], ...]


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

    labeled_postings = tuple(
        (posting, labels_by_hash[posting.dedup_hash])
        for posting in postings
        if posting.dedup_hash in labels_by_hash
    )
    matched_labels = tuple(label for _, label in labeled_postings)
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
        labeled_postings=labeled_postings,
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


def _parse_reference_modes(values: Sequence[str] | None) -> list[str]:
    modes = [
        mode.strip()
        for value in (values or ["blend"])
        for mode in value.split(",")
        if mode.strip()
    ]
    if not modes:
        raise ValueError("--reference-mode must name at least one mode")
    invalid = set(modes) - REFERENCE_MODES
    if invalid:
        raise ValueError("Unknown reference mode(s): " + ", ".join(sorted(invalid)))
    if len(set(modes)) != len(modes):
        raise ValueError("--reference-mode must not repeat a mode")
    return modes


def _parse_cut_depths(value: str) -> list[int]:
    try:
        depths = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError(
            "--cut-depths must be comma-separated integer percentages"
        ) from exc
    if not depths or any(depth < 1 or depth > 100 for depth in depths):
        raise ValueError("--cut-depths must contain percentages in 1..100")
    if depths != sorted(set(depths)):
        raise ValueError("--cut-depths must be sorted and contain no duplicates")
    return depths


def _reference_texts(
    reference_mode: str,
    profile: dict[str, object],
    target_titles: Sequence[str],
    goal_summary: str,
) -> tuple[list[str], str]:
    if reference_mode == "blend":
        return [build_reference_text(profile, target_titles, goal_summary)], "max"
    if reference_mode == "keywords":
        return [build_keywords_reference_text(target_titles)], "max"
    if reference_mode == "keyword-max":
        return build_per_keyword_reference_texts(target_titles), "max"
    if reference_mode == "keyword-mean":
        return build_per_keyword_reference_texts(target_titles), "mean"
    if reference_mode == "skills-max":
        return [
            *build_per_keyword_reference_texts(target_titles),
            build_skills_reference_text(profile),
        ], "max"
    if reference_mode == "exemplar":
        return [], "max"
    raise ValueError(f"Unknown reference mode: {reference_mode!r}")


def _embedding_client(provider: str, base_url: str) -> OpenAI:
    if provider == "ollama":
        return OpenAI(base_url=base_url, api_key="local-embedding-server")
    if provider == "openai":
        return OpenAI()
    raise ValueError(f"Unsupported provider: {provider}")


def _resolve_embeddings(
    cache: dict[str, tuple[float, ...]],
    requested: dict[CacheIdentity, str],
    *,
    cache_path: Path,
    provider: str,
    base_url: str,
    model: str,
    embedding_batch_size: int,
    client_holder: list[Any | None],
) -> dict[str, int]:
    misses = {
        identity: text
        for identity, text in requested.items()
        if identity.key not in cache
    }
    if not misses:
        return {
            "cache_hits": len(requested),
            "cache_misses": 0,
            "provider_api_batches": 0,
        }
    if client_holder[0] is None:
        client_holder[0] = _embedding_client(provider, base_url)
    fetched, vectors_requested, api_batches = fetch_missing_embeddings(
        client_holder[0], model, misses, batch_size=embedding_batch_size
    )
    cache.update(fetched)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8") as cache_file:
        for identity in misses:
            cache_file.write(
                json.dumps(
                    _cache_entry(identity, fetched[identity.key]), separators=(",", ":")
                )
                + "\n"
            )
    return {
        "cache_hits": len(requested) - len(misses),
        "cache_misses": vectors_requested,
        "provider_api_batches": api_batches,
    }


def bottom_drop_curve(
    ranked: Sequence[RankedPosting],
    labels_by_posting_id: dict[int, ScoredLabel],
    cut_depths: Sequence[int],
) -> tuple[list[dict[str, int | float | None]], int]:
    """Measure good-job loss and junk purity after dropping each rank-space tail."""
    good_total = sum(
        label.fit_score is not None and label.fit_score >= 4
        for label in labels_by_posting_id.values()
    )
    rows: list[dict[str, int | float | None]] = []
    for cut_depth_pct in cut_depths:
        jobs_cut = math.floor(len(ranked) * cut_depth_pct / 100)
        dropped = ranked[-jobs_cut:] if jobs_cut else []
        dropped_labels = [labels_by_posting_id[id(item.posting)] for item in dropped]
        good_lost = sum(
            label.fit_score is not None and label.fit_score >= 4
            for label in dropped_labels
        )
        junk_dropped = sum(
            label.fit_score is not None and label.fit_score <= 2
            for label in dropped_labels
        )
        rows.append(
            {
                "cut_depth_pct": cut_depth_pct,
                "jobs_cut": jobs_cut,
                "good_lost": good_lost,
                "good_lost_pct": good_lost / good_total if good_total else None,
                "good_kept": good_total - good_lost,
                "dropped_purity": junk_dropped / jobs_cut if jobs_cut else None,
            }
        )
    max_cut_pct = max(
        (
            int(row["cut_depth_pct"])
            for row in rows
            if row["good_lost_pct"] is not None and float(row["good_lost_pct"]) <= 0.07
        ),
        default=0,
    )
    return rows, max_cut_pct


def _curve_filename(cohort: CohortKey, reference_mode: str) -> str:
    def safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unknown"

    return (
        "curve-"
        + "-".join(
            [
                safe(cohort.profile_version),
                safe(cohort.provider),
                safe(cohort.model),
                safe(reference_mode),
            ]
        )
        + ".csv"
    )


def _write_curve_csv(
    path: Path, curve: Sequence[dict[str, int | float | None]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=(
                "cut_depth_pct",
                "jobs_cut",
                "good_lost",
                "good_lost_pct",
                "good_kept",
                "dropped_purity",
            ),
        )
        writer.writeheader()
        writer.writerows(curve)


def score_eligible_cohorts(
    audits: Sequence[RunAudit],
    *,
    profile: dict[str, object],
    target_titles: Sequence[str],
    goal_summary: str,
    reference_modes: Sequence[str],
    provider: str,
    model: str,
    base_url: str,
    prefix_scheme: str,
    cache_path: Path,
    curve_output_dir: Path,
    cut_depths: Sequence[int],
    embedding_batch_size: int,
    allow_ground_truth_reference: bool,
    embedding_client: Any | None = None,
) -> dict[str, object]:
    """Score every density-eligible compatible cohort and persist its curves."""
    if prefix_scheme not in SCHEMAS_BY_PREFIX_SCHEME:
        raise ValueError(f"Unknown prefix scheme: {prefix_scheme!r}")
    endpoint = endpoint_identity(provider, base_url)
    schemas = SCHEMAS_BY_PREFIX_SCHEME[prefix_scheme]
    grouped: defaultdict[CohortKey, list[tuple[Posting, ScoredLabel]]] = defaultdict(
        list
    )
    for audit in audits:
        for posting, label in audit.labeled_postings:
            grouped[label.cohort].append((posting, label))

    eligible = {
        cohort: entries
        for cohort, entries in grouped.items()
        if eligibility_verdict(
            len(entries),
            sum(
                label.fit_score is not None and label.fit_score >= 4
                for _, label in entries
            ),
        )["shadow_eligible"]
    }
    if not eligible:
        log.warning(
            "No compatible cohort meets the shadow eligibility threshold; skipping scoring"
        )
        return {
            "cache_path": str(cache_path),
            "eligible_cohort_count": 0,
            "curves": [],
            "summaries": [],
        }

    try:
        cache = parse_cache_jsonl(cache_path.read_text(encoding="utf-8"), cache_path)
    except FileNotFoundError:
        cache = {}
    except OSError as exc:
        raise OSError(f"Could not read embedding cache {cache_path}: {exc}") from exc

    client_holder = [embedding_client]
    curves: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for cohort, entries in sorted(
        eligible.items(),
        key=lambda item: (item[0].profile_version, item[0].provider, item[0].model),
    ):
        postings = [posting for posting, _ in entries]
        labels_by_posting_id = {id(posting): label for posting, label in entries}
        ai_fits = {posting.dedup_hash: label.fit_score for posting, label in entries}
        job_identities = []
        requested: dict[CacheIdentity, str] = {}
        for posting in postings:
            text = apply_prefix_scheme(
                build_job_text(posting, "title"),
                role="job",
                prefix_scheme=prefix_scheme,
            )
            identity = cache_identity(
                schema_version=schemas["title"],
                provider=provider,
                endpoint=endpoint,
                model=model,
                text=text,
            )
            job_identities.append(identity)
            requested[identity] = text

        for reference_mode in reference_modes:
            if reference_mode == "exemplar" and not allow_ground_truth_reference:
                raise ValueError(
                    "exemplar mode requires --allow-ground-truth-reference"
                )
            reference_texts, pool = _reference_texts(
                reference_mode, profile, target_titles, goal_summary
            )
            reference_identities = []
            mode_requested = dict(requested)
            for reference_text in reference_texts:
                text = apply_prefix_scheme(
                    reference_text, role="reference", prefix_scheme=prefix_scheme
                )
                identity = cache_identity(
                    schema_version=schemas["reference"],
                    provider=provider,
                    endpoint=endpoint,
                    model=model,
                    text=text,
                )
                reference_identities.append(identity)
                mode_requested[identity] = text
            cache_statistics = _resolve_embeddings(
                cache,
                mode_requested,
                cache_path=cache_path,
                provider=provider,
                base_url=base_url,
                model=model,
                embedding_batch_size=embedding_batch_size,
                client_holder=client_holder,
            )
            job_vectors = [cache[identity.key] for identity in job_identities]
            if reference_mode == "exemplar":
                good_vectors = [
                    vector
                    for vector, posting in zip(job_vectors, postings, strict=True)
                    if labels_by_posting_id[id(posting)].fit_score is not None
                    and labels_by_posting_id[id(posting)].fit_score >= 4
                ]
                if not good_vectors:
                    raise ValueError(
                        "exemplar mode requires at least one good labeled job"
                    )
                reference_vectors = [
                    [
                        sum(vector[index] for vector in good_vectors)
                        / len(good_vectors)
                        for index in range(len(good_vectors[0]))
                    ]
                ]
            else:
                reference_vectors = [
                    cache[identity.key] for identity in reference_identities
                ]
            ranked = rank_by_scores(
                postings, pool_scores(job_vectors, reference_vectors, pool), ai_fits
            )
            curve, max_cut_pct = bottom_drop_curve(
                ranked, labels_by_posting_id, cut_depths
            )
            csv_path = curve_output_dir / _curve_filename(cohort, reference_mode)
            _write_curve_csv(csv_path, curve)
            cohort_data = cohort.as_dict()
            curves.append(
                {
                    "cohort": cohort_data,
                    "reference_mode": reference_mode,
                    "curve_csv": str(csv_path),
                    "cache_statistics": cache_statistics,
                    "curve": curve,
                }
            )
            summaries.append(
                {
                    "cohort": cohort_data,
                    "reference_mode": reference_mode,
                    "max_cut_pct": max_cut_pct,
                    "good_loss_budget_pct": 7,
                }
            )
    return {
        "cache_path": str(cache_path),
        "eligible_cohort_count": len(eligible),
        "curves": curves,
        "summaries": summaries,
    }


def _load_scoring_profile(path: Path) -> dict[str, object]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load profile {path}: {exc}") from exc
    return validate_profile(loaded, path)


def format_scoring_summary(scoring: dict[str, object]) -> str:
    """Render the Table-D max-cut rows after the audit's density summary."""
    summaries = scoring["summaries"]
    assert isinstance(summaries, list)
    lines = ["", "Bottom-drop curve max cuts (<=7% good jobs lost):"]
    if not summaries:
        return "\n".join(lines + ["No eligible cohorts were scored."])
    lines.append("profile_version\tprovider\tmodel\treference_mode\tmax_cut_pct")
    for summary in summaries:
        assert isinstance(summary, dict)
        cohort = summary["cohort"]
        assert isinstance(cohort, dict)
        lines.append(
            f"{cohort['profile_version']}\t{cohort['provider']}\t{cohort['model']}\t"
            f"{summary['reference_mode']}\t{summary['max_cut_pct']}"
        )
    return "\n".join(lines)


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
    parser.add_argument(
        "--score",
        action="store_true",
        help="Score eligible cohorts and emit bottom-drop curves",
    )
    parser.add_argument(
        "--reference-mode",
        action="append",
        help="Reference mode; repeat or pass a comma-separated list (default: blend)",
    )
    parser.add_argument(
        "--profile", type=Path, help="Candidate profile YAML (required with --score)"
    )
    parser.add_argument(
        "--target-title", action="append", help="Target title (required with --score)"
    )
    parser.add_argument("--goal-summary", default="")
    parser.add_argument("--provider", choices=("openai", "ollama"), default="ollama")
    parser.add_argument("--model", default="nomic-embed-text-v1.5")
    parser.add_argument("--base-url", default="http://localhost:8080/v1")
    parser.add_argument("--prefix-scheme", choices=("none", "nomic"), default="nomic")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument(
        "--curve-output-dir", type=Path, default=DEFAULT_CURVE_OUTPUT_DIR
    )
    parser.add_argument(
        "--cut-depths",
        default=",".join(str(depth) for depth in DEFAULT_CUT_DEPTHS),
        help="Comma-separated rank-space drop percentages (default: 10,15,...,70)",
    )
    parser.add_argument("--embedding-batch-size", type=int, default=100)
    parser.add_argument(
        "--allow-ground-truth-reference",
        action="store_true",
        help="Allow the diagnostic exemplar reference mode",
    )
    return parser


def run(
    args: argparse.Namespace, *, embedding_client: Any | None = None
) -> dict[str, object]:
    report = audit_user_runs(args.runs_root, args.user_slug)
    if getattr(args, "score", False):
        profile_path = getattr(args, "profile", None)
        target_titles = getattr(args, "target_title", None)
        if profile_path is None:
            raise ValueError("--score requires --profile")
        if not target_titles:
            raise ValueError("--score requires at least one --target-title")
        if args.embedding_batch_size < 1:
            raise ValueError("--embedding-batch-size must be at least 1")
        audits = [
            audit_run(run_dir)
            for run_dir in discover_run_dirs(args.runs_root, args.user_slug)
        ]
        report["scoring"] = score_eligible_cohorts(
            audits,
            profile=_load_scoring_profile(profile_path),
            target_titles=target_titles,
            goal_summary=args.goal_summary,
            reference_modes=_parse_reference_modes(args.reference_mode),
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            prefix_scheme=args.prefix_scheme,
            cache_path=args.cache,
            curve_output_dir=args.curve_output_dir,
            cut_depths=_parse_cut_depths(args.cut_depths),
            embedding_batch_size=args.embedding_batch_size,
            allow_ground_truth_reference=args.allow_ground_truth_reference,
            embedding_client=embedding_client,
        )
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(format_summary(report))
    if "scoring" in report:
        scoring = report["scoring"]
        assert isinstance(scoring, dict)
        print(format_scoring_summary(scoring))
    return report


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
