from __future__ import annotations

import argparse

# from curses import raw
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from job_scraper.config import ConfigError
from utils.git_info import get_git_metadata

from .models import (
    SCHEMA_VERSION,
    CountryDetectionConfig,
    LocalAreaConfig,
    PrefilterConfig,
    PrefilterRoute,
    RoutingConfig,
)

from .str_utils import (
    check_banned_terms,
    merge_country_aliases,
    _country_hits,
    _flatten_strings,
    _local_match,
    _has_phrase,
)

log = logging.getLogger(__name__)

DEFAULT_INPUT_PATH = Path("data/raw")
DEFAULT_REMOTE_OUT = Path("data/prefiltered/remote_filter_input.jsonl")
DEFAULT_LOCAL_OUT = Path("data/local/local_jobs.jsonl")
DEFAULT_TRASH_OUT = Path("data/trash/prefilter_trash.jsonl")
DEFAULT_CONFIG_PATH = Path("config/agent/prefilter.yml")

_REMOTE_HINTS = [
    "remote",
    "work from home",
    "work remotely",
    "distributed team",
    "telecommute",
    "wfh",
    "anywhere",
]


@dataclass
class RouteDecision:
    route: PrefilterRoute
    reason: str
    matched_rules: list[str]
    rule_trace: list[str]
    routing_decision_source: str
    country_hits: list[str]
    country_alias_hits: dict[str, str]


@dataclass
class _ResolvedPrefilterConfig:
    config: PrefilterConfig
    aliases: dict[str, list[str]]


def _expand_env_vars(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.environ.get(name)
        if value is None:
            raise ConfigError(f"Environment variable ${{{name}}} is not set")
        return value

    return re.sub(r"\$\{([^}]+)\}", _sub, text)


def _load_jobs(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    paths = [p] if p.is_file() else sorted(p.glob("*.jsonl"))
    jobs: list[dict[str, Any]] = []
    for file in paths:
        with open(file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    jobs.append(json.loads(line))
    return jobs


def _config_dict(cfg: PrefilterConfig) -> dict[str, Any]:
    return asdict(cfg)


def load_prefilter_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> _ResolvedPrefilterConfig:
    raw_text = _expand_env_vars(Path(path).read_text())
    raw = yaml.safe_load(raw_text) or {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Prefilter config must be a YAML mapping, got {type(raw).__name__}"
        )

    country = str(raw.get("country", "USA"))
    cd = raw.get("country_detection") or {}
    if not isinstance(cd, dict):
        raise ConfigError("country_detection must be a YAML mapping")
    local_area = raw.get("local_area") or {}
    if not isinstance(local_area, dict):
        raise ConfigError("local_area must be a YAML mapping")
    routing = raw.get("routing") or {}
    if not isinstance(routing, dict):
        raise ConfigError("routing must be a YAML mapping")

    filter_terms_raw = raw.get("filter_terms") or {}
    if not isinstance(filter_terms_raw, dict):
        raise ConfigError("filter_terms must be a YAML mapping")

    filter_terms = {
        str(k): [str(v) for v in (vals or [])] for k, vals in filter_terms_raw.items()
    }

    config = PrefilterConfig(
        country=country,
        country_detection=CountryDetectionConfig(
            enabled=bool(cd.get("enabled", True)),
            sources=[
                str(x) for x in (cd.get("sources") or ["location", "description"])
            ],
            aliases={
                str(k): [str(v) for v in (vals or [])]
                for k, vals in (cd.get("aliases") or {}).items()
            },
            unknown_policy=str(cd.get("unknown_policy", "continue")),
        ),
        local_area=LocalAreaConfig(
            allowed_locations=[
                str(x) for x in (local_area.get("allowed_locations") or [])
            ],
            home_location=(
                str(local_area["home_location"])
                if local_area.get("home_location")
                else None
            ),
        ),
        routing=RoutingConfig(
            route_local_jobs=bool(routing.get("route_local_jobs", True)),
            route_remote_candidates=bool(routing.get("route_remote_candidates", True)),
            reject_non_us=bool(routing.get("reject_non_us", True)),
            prefer_search_params_as_weak_signal=bool(
                routing.get("prefer_search_params_as_weak_signal", True)
            ),
        ),
        filter_terms=filter_terms,
    )
    return _ResolvedPrefilterConfig(
        config=config,
        aliases=merge_country_aliases(country, config.country_detection.aliases),
    )


def build_prefilter_metadata(
    cfg: PrefilterConfig,
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    git_meta = get_git_metadata()
    config_hash = sha256(
        json.dumps(_config_dict(cfg), sort_keys=True).encode()
    ).hexdigest()[:12]
    return {
        "schema_version": SCHEMA_VERSION,
        "config_hash": config_hash,
        "config_file": Path(config_path).name,
        "commit": git_meta["commit"],
        "dirty": git_meta["dirty"],
        "routed_at": git_meta["timestamp"],
        "local_policy_version": SCHEMA_VERSION,
    }


def route_job(job: dict[str, Any], resolved: _ResolvedPrefilterConfig) -> RouteDecision:
    """
    Apply routing rules to a single job and return a RouteDecision with the route, reason, matched rules, and trace info.

    Composed of modular checks for country detection, banned terms, local area matching, and remote hints, with detailed trace logging for debugging and analysis.
    """

    cfg = resolved.config
    target_country = cfg.country
    company = str(job.get("company") or "")
    title = str(job.get("title") or "")
    location = str(job.get("location") or "")
    description = str(job.get("description") or "")
    search_params = job.get("search_params") or {}
    flat_search_params = _flatten_strings(search_params)
    combined_texts = [title, location, description]
    filter_terms = getattr(cfg, "filter_terms", {}) or {}

    trace: list[str] = []
    matched_rules: list[str] = []

    # Check 1: Route based on country detection
    country_sources = []
    for source_name in cfg.country_detection.sources:
        if source_name == "location":
            country_sources.append(location)
        elif source_name == "description":
            country_sources.append(description)
        elif source_name == "title":
            country_sources.append(title)
        elif source_name == "search_params":
            country_sources.extend(flat_search_params)

    hits, alias_hits, hit_source = _country_hits(
        country_sources, resolved.aliases, target_country
    )
    trace.append(f"country_check:hits={hits or ['none']}")

    if cfg.routing.reject_non_us and hits and target_country not in hits:
        other = hits[0]
        trace.append(f"country_check:reject:{other}")
        matched_rules.append(f"country:{other}")
        return RouteDecision(
            route="prefilter_reject",
            reason="non_selected_country",
            matched_rules=matched_rules,
            rule_trace=trace,
            routing_decision_source=hit_source or "location",
            country_hits=hits,
            country_alias_hits=alias_hits,
        )

    # Check 2: Check for banned terms in title/location/description/search_params
    banned, matched_term = check_banned_terms(
        company, title, location, description, filter_terms
    )

    if banned:
        matched_rules.append(f"banned_term:{matched_term}")
        trace.append(f"banned_term:reject:{matched_term}")
        return RouteDecision(
            route="prefilter_reject",
            reason="banned_term",
            matched_rules=matched_rules,
            rule_trace=trace,
            routing_decision_source="company/title/location/description",
            country_hits=hits,
            country_alias_hits=alias_hits,
        )

    # Check 3: Route based on local area allowlist
    local_ok, local_source = _local_match(
        job, cfg, flat_search_params=flat_search_params
    )
    trace.append(f"local_check:{'pass' if local_ok else 'miss'}")
    if local_ok and cfg.routing.route_local_jobs:
        matched_rules.append("local_area_allowlist")
        return RouteDecision(
            route="local_candidate",
            reason="allowed_local_location",
            matched_rules=matched_rules,
            rule_trace=trace,
            routing_decision_source=local_source or "location",
            country_hits=hits,
            country_alias_hits=alias_hits,
        )

    # Check 4: Route based on remote hints
    combined_texts = [title, location, description]
    if cfg.routing.prefer_search_params_as_weak_signal:
        combined_texts.extend(flat_search_params)

    remote_hit, remote_phrase = _has_phrase(combined_texts, _REMOTE_HINTS)
    trace.append(f"signal_check:remote={remote_hit}")

    if cfg.routing.route_remote_candidates:
        if remote_hit:
            matched_rules.append(f"remote:{remote_phrase}")
            trace.append(f"signal_check:route_remote:{remote_phrase}")
        else:
            trace.append("signal_check:route_remote:ambiguous")
        return RouteDecision(
            route="remote_filter_candidate",
            reason="remote_or_ambiguous",
            matched_rules=matched_rules,
            rule_trace=trace,
            routing_decision_source="title/location/description",
            country_hits=hits,
            country_alias_hits=alias_hits,
        )

    # Check 5: Fallthrough for jobs that didn't match previous checks.
    matched_rules.append("routing_disabled:remote_candidates")
    return RouteDecision(
        route="prefilter_reject",
        reason="routing_disabled",
        matched_rules=matched_rules,
        rule_trace=trace,
        routing_decision_source="title/location/description",
        country_hits=hits,
        country_alias_hits=alias_hits,
    )


def _annotate_job(
    job: dict[str, Any],
    decision: RouteDecision,
    base_metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata = {
        **base_metadata,
        "matched_rules": decision.matched_rules,
        "rule_trace": decision.rule_trace,
        "routing_decision_source": decision.routing_decision_source,
        "country_hits": decision.country_hits,
        "country_alias_hits": decision.country_alias_hits,
    }
    annotated: dict[str, Any] = {
        **job,
        "_prefilter_result": decision.route,
        "_prefilter_reason": decision.reason,
        "_prefilter_metadata": metadata,
    }
    if decision.route == "local_candidate":
        annotated["remote_classification"] = "location_restricted"
    return annotated


def run_prefilter(
    *,
    input_path: str | Path = DEFAULT_INPUT_PATH,
    remote_out: str | Path = DEFAULT_REMOTE_OUT,
    local_out: str | Path = DEFAULT_LOCAL_OUT,
    trash_out: str | Path = DEFAULT_TRASH_OUT,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Main entry point for the prefilter router. Reads raw jobs, applies routing rules, and writes annotated jobs to remote/local/trash outputs.
    """

    input_path = Path(input_path)
    remote_out = Path(remote_out)
    local_out = Path(local_out)
    trash_out = Path(trash_out)

    resolved = load_prefilter_config(config_path)
    cfg = resolved.config
    jobs = _load_jobs(input_path)
    if not jobs:
        raise FileNotFoundError(f"No jobs found in {input_path}")

    base_metadata = build_prefilter_metadata(cfg, config_path=config_path)
    base_metadata["selected_country"] = cfg.country
    base_metadata["config_path"] = str(config_path)

    if dry_run:
        counts = {
            "remote_filter_candidate": 0,
            "local_candidate": 0,
            "prefilter_reject": 0,
        }
        for job in jobs:
            decision = route_job(job, resolved)
            counts[decision.route] += 1
        log.info(
            "Dry run — %d jobs | remote=%d | local=%d | reject=%d",
            len(jobs),
            counts["remote_filter_candidate"],
            counts["local_candidate"],
            counts["prefilter_reject"],
        )
        return {"total": len(jobs), **counts}

    remote_out.parent.mkdir(parents=True, exist_ok=True)
    local_out.parent.mkdir(parents=True, exist_ok=True)
    trash_out.parent.mkdir(parents=True, exist_ok=True)

    counts = {"remote_filter_candidate": 0, "local_candidate": 0, "prefilter_reject": 0}
    with (
        remote_out.open("w", encoding="utf-8") as remote_f,
        local_out.open("w", encoding="utf-8") as local_f,
        trash_out.open("w", encoding="utf-8") as trash_f,
    ):
        for job in jobs:
            decision = route_job(job, resolved)
            enriched = _annotate_job(job, decision, base_metadata)
            line = json.dumps(enriched)
            if decision.route == "remote_filter_candidate":
                remote_f.write(line + "\n")
            elif decision.route == "local_candidate":
                local_f.write(line + "\n")
            else:
                trash_f.write(line + "\n")
            counts[decision.route] += 1

    log.info(
        "Done — %d jobs | remote=%d | local=%d | reject=%d",
        len(jobs),
        counts["remote_filter_candidate"],
        counts["local_candidate"],
        counts["prefilter_reject"],
    )
    return {"total": len(jobs), **counts}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_prefilter.py",
        description="Deterministically route raw jobs before the remote filter.",
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--remote-out", default=str(DEFAULT_REMOTE_OUT))
    parser.add_argument("--local-out", default=str(DEFAULT_LOCAL_OUT))
    parser.add_argument("--trash-out", default=str(DEFAULT_TRASH_OUT))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        run_prefilter(
            input_path=args.input,
            remote_out=args.remote_out,
            local_out=args.local_out,
            trash_out=args.trash_out,
            config_path=args.config,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        log.error(str(exc))
        raise SystemExit(1) from exc
