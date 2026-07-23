"""Queue-driven scrape worker (Phase 13 spec §8 step 2).

Loop forever (or until cancelled):

1. ``claim_next`` — atomic lease (source-serialization in SQL).
2. Invoke the per-source scrape via ``scrape_fn``.
3. Apply the user's policies.prefilter inline — currently just
   ``excluded_title_terms`` (cheap title substring drop). Spec §11.4.
4. Write surviving postings to ``runs/<slug>/<run_id>/scrape/<source>.jsonl``.
5. ``mark_succeeded`` with the count, or on any exception ``mark_failed``
   with the full traceback (per-user failure isolation, §7).

Single-process, single-threaded by design. Concurrency between sources
already comes from the source-serialization claim: pending rows for
different sources can be claimed by separate calls without the worker
having to schedule them. (Slice 7 may move to an async loop with multiple
in-flight non-conflicting jobs; this slice keeps it dumb.)

``scrape_fn`` is injectable to keep tests deterministic. Production wires
in :func:`default_scrape_fn` which writes the per-source payload to a
temporary YAML, invokes ``job_scraper.config.load_config`` on it, and runs
the resulting scrapers.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

import psycopg
import yaml
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from pipeline.queue import claim_next, mark_failed, mark_succeeded
from prefilter.embedding import (
    Posting,
    SCHEMAS_BY_PREFIX_SCHEME,
    _cache_entry,
    apply_prefix_scheme,
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
from user_config import UserPolicies

log = logging.getLogger(__name__)

ScrapeFn = Callable[[str, dict[str, Any], "psycopg.Connection | None"], Iterable[Any]]
ReferenceMode = Literal[
    "blend", "keywords", "keyword-max", "keyword-mean", "skills-max"
]
_COMPANIES_PREFILTER_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "agent" / "companies_prefilter.yml"
)


@dataclass(frozen=True)
class EmbeddingVetoConfig:
    """Resolved system and optional per-user companies-veto policy."""

    enabled: bool
    cut_depth: float
    reference_mode: ReferenceMode
    provider: Literal["ollama"]
    base_url: str
    model: str
    prefix_scheme: Literal["none", "nomic"]
    cache_path: Path
    embedding_batch_size: int


class _EmbeddingVetoConfigFile(BaseModel):
    """Strict on-disk schema so a malformed enabled veto cannot degrade silently."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cut_depth: float = Field(default=0.33, ge=0, le=1)
    reference_mode: ReferenceMode = "blend"
    provider: Literal["ollama"] = "ollama"
    base_url: str = "http://localhost:8080/v1"
    model: str = "nomic-embed-text-v1.5"
    prefix_scheme: Literal["none", "nomic"] = "nomic"
    cache_path: Path = Path("data/cache/companies_prefilter_embeddings.jsonl")
    embedding_batch_size: int = Field(default=100, ge=1)


"""``(source, query_payload, conn) -> iterable of scraped postings`` (either
dataclass instances or already-dict). The worker calls ``asdict`` on any
dataclass, then JSON-serializes; non-dataclass dict inputs pass through.
``conn`` is forwarded to ``load_config`` so the companies section can resolve
normalized names to verified ATS slugs via ``raw.company_aliases``."""


# ---------------------------------------------------------------------------
# Default (production) scrape_fn
# ---------------------------------------------------------------------------


def default_scrape_fn(
    source: str,
    query_payload: dict[str, Any],
    conn: "psycopg.Connection | None" = None,
) -> list[Any]:
    """Real scrape: write payload to a temp YAML, load_config, run scrapers.

    ``query_payload`` is the per-source slice the planner stored
    (``{source: <section>, "global": {...}}``). The temp YAML lives only for
    the duration of the call.  ``conn`` is forwarded so the companies section
    can hit ``raw.company_aliases`` for verified slugs.
    """
    from job_scraper.config import load_config

    tmp_yaml = Path(f".pipeline-scrape-input-{source}.yml")
    tmp_yaml.write_text(yaml.safe_dump(query_payload, sort_keys=False))
    try:
        scrapers = load_config(tmp_yaml, conn=conn)
    finally:
        try:
            tmp_yaml.unlink()
        except FileNotFoundError:
            pass

    jobs: list[Any] = []
    for s in scrapers:
        # Per-scraper exceptions bubble up — the worker catches them at the
        # job boundary and marks the whole (user, source) job failed. That's
        # blunter than the single-user CLI (which records permanent skips
        # per-scraper), but Phase 13's per-user retry surface is "re-run the
        # queue", not partial-source resumption (spec §7).
        jobs.extend(s.scrape())
    return jobs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(email: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "_", email.strip().lower()).replace(".", "_")


def run_user_dir(runs_dir: Path, run_id: str, email: str) -> Path:
    """Per-user artifact dir for a run, partitioned **run-first**:
    ``<runs_dir>/<run_id>/<slug>``. Run-first co-locates every user (and the
    shared ``_consolidated/`` stage) under one run dir, so a whole run is one
    subtree to upload, ingest, or drop. Canonical home for the layout so the
    planner, worker, consolidation, and scoring agree on one definition."""
    return runs_dir / run_id / _slug(email)


def _to_dict(job: Any) -> dict[str, Any]:
    """Normalize a scraped posting to a plain dict for serialization."""
    if dataclasses.is_dataclass(job) and not isinstance(job, type):
        return dataclasses.asdict(job)
    if isinstance(job, dict):
        return job
    raise TypeError(
        f"scrape_fn produced an unsupported posting type: {type(job).__name__}; "
        "expected dataclass instance or dict"
    )


def _apply_title_filter(
    jobs: list[dict[str, Any]], excluded_terms: list[str]
) -> list[dict[str, Any]]:
    """Drop postings whose title contains any of ``excluded_terms`` (case-
    insensitive substring match). Empty list of terms = no-op."""
    if not excluded_terms:
        return jobs
    lowered = [t.strip().lower() for t in excluded_terms if t.strip()]
    if not lowered:
        return jobs

    def _keep(job: dict[str, Any]) -> bool:
        title = (job.get("title") or "").lower()
        return not any(term in title for term in lowered)

    return [j for j in jobs if _keep(j)]


def _load_embedding_veto_config(policies: UserPolicies) -> EmbeddingVetoConfig:
    """Load the system veto config and apply a user's explicit policy overrides."""
    try:
        raw = yaml.safe_load(_COMPANIES_PREFILTER_CONFIG_PATH.read_text())
    except OSError as exc:
        raise OSError(
            f"Could not load companies embedding-veto config "
            f"{_COMPANIES_PREFILTER_CONFIG_PATH}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Could not parse companies embedding-veto config "
            f"{_COMPANIES_PREFILTER_CONFIG_PATH}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"Companies embedding-veto config {_COMPANIES_PREFILTER_CONFIG_PATH} "
            "must be a YAML mapping"
        )
    loaded = _EmbeddingVetoConfigFile.model_validate(raw)
    config = EmbeddingVetoConfig(
        enabled=loaded.enabled,
        cut_depth=loaded.cut_depth,
        reference_mode=loaded.reference_mode,
        provider=loaded.provider,
        base_url=loaded.base_url,
        model=loaded.model,
        prefix_scheme=loaded.prefix_scheme,
        cache_path=loaded.cache_path,
        embedding_batch_size=loaded.embedding_batch_size,
    )
    if policies.prefilter.embedding_veto_enabled is not None:
        config = replace(config, enabled=policies.prefilter.embedding_veto_enabled)
    if policies.prefilter.embedding_veto_depth is not None:
        config = replace(config, cut_depth=policies.prefilter.embedding_veto_depth)
    return config


def _load_reference_texts(run_dir: Path, reference_mode: ReferenceMode) -> list[str]:
    """Build canonical reference inputs from this user's run artifacts."""
    profile_path = run_dir / "candidate_profile.yml"
    search_path = run_dir / "search.yml"
    try:
        profile_raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load profile {profile_path}: {exc}") from exc
    profile = validate_profile(profile_raw, profile_path)

    try:
        search_raw = yaml.safe_load(search_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load search config {search_path}: {exc}") from exc
    if not isinstance(search_raw, dict):
        raise ValueError(
            f"Malformed search config {search_path}: expected a YAML mapping"
        )
    roles = search_raw.get("roles")
    target_titles = roles.get("target_titles") if isinstance(roles, dict) else None
    if not isinstance(target_titles, dict):
        raise ValueError(
            f"Malformed search config {search_path}: roles.target_titles is required "
            "for the enabled embedding veto"
        )
    preferred = target_titles.get("preferred")
    exploratory = target_titles.get("exploratory", [])
    if (
        not isinstance(preferred, list)
        or not isinstance(exploratory, list)
        or not all(isinstance(title, str) for title in [*preferred, *exploratory])
    ):
        raise ValueError(
            f"Malformed search config {search_path}: target title lists must contain strings"
        )
    search_profile = search_raw.get("search_profile", {})
    if not isinstance(search_profile, dict):
        raise ValueError(
            f"Malformed search config {search_path}: search_profile must be a mapping"
        )
    goal_summary = search_profile.get("goal_summary", "")
    if not isinstance(goal_summary, str):
        raise ValueError(
            f"Malformed search config {search_path}: search_profile.goal_summary "
            "must be a string"
        )
    titles = [*preferred, *exploratory]
    if reference_mode == "blend":
        return [build_reference_text(profile, titles, goal_summary)]
    if reference_mode == "keywords":
        return [build_keywords_reference_text(titles)]
    if reference_mode in {"keyword-max", "keyword-mean"}:
        return build_per_keyword_reference_texts(titles)
    if reference_mode == "skills-max":
        return build_per_keyword_reference_texts(titles) + [
            build_skills_reference_text(profile)
        ]
    raise ValueError(f"Unknown reference mode: {reference_mode!r}")


def _load_embedding_cache(cache_path: Path) -> dict[str, tuple[float, ...]]:
    try:
        return parse_cache_jsonl(cache_path.read_text(encoding="utf-8"), cache_path)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise OSError(f"Could not read embedding cache {cache_path}: {exc}") from exc


def _embedding_client(config: EmbeddingVetoConfig) -> OpenAI:
    """Construct the OpenAI-compatible local nomic client only on a cache miss."""
    return OpenAI(base_url=config.base_url, api_key="ollama")


def _posting_for_embedding(job: dict[str, Any], index: int) -> Posting:
    title = job.get("title")
    company = job.get("company")
    dedup_hash = job.get("dedup_hash")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Companies posting {index}: title must be a non-empty string")
    if not isinstance(company, str) or not company.strip():
        raise ValueError(
            f"Companies posting {index}: company must be a non-empty string"
        )
    if not isinstance(dedup_hash, str) or not dedup_hash.strip():
        raise ValueError(
            f"Companies posting {index}: dedup_hash must be a non-empty string"
        )
    return Posting(
        title=" ".join(title.split()),
        company=" ".join(company.split()),
        dedup_hash=dedup_hash.strip(),
        description="",
        source_url="",
        description_fallback=True,
    )


def _apply_embedding_veto(
    jobs: list[dict[str, Any]],
    *,
    reference_text: str | list[str],
    config: EmbeddingVetoConfig,
    cache: dict[str, tuple[float, ...]],
) -> list[dict[str, Any]]:
    """Drop the globally lowest-ranked configured fraction of a companies pool.

    The cache is content-addressed by the shared embedding core. Cache misses are
    appended only after the provider returns a complete, validated response.
    """
    if not jobs or config.cut_depth == 0:
        return jobs
    schemas = SCHEMAS_BY_PREFIX_SCHEME[config.prefix_scheme]
    endpoint = endpoint_identity(config.provider, config.base_url)
    postings = [_posting_for_embedding(job, index) for index, job in enumerate(jobs)]

    reference_texts = (
        [reference_text] if isinstance(reference_text, str) else reference_text
    )
    if not reference_texts:
        raise ValueError("Embedding veto requires at least one reference text")
    reference_identities = []
    requested = {}
    for text in reference_texts:
        reference_input = apply_prefix_scheme(
            text, role="reference", prefix_scheme=config.prefix_scheme
        )
        identity = cache_identity(
            schema_version=schemas["reference"],
            provider=config.provider,
            endpoint=endpoint,
            model=config.model,
            text=reference_input,
        )
        reference_identities.append(identity)
        requested[identity] = reference_input
    job_identities = []
    for posting in postings:
        job_input = apply_prefix_scheme(
            posting.title, role="job", prefix_scheme=config.prefix_scheme
        )
        identity = cache_identity(
            schema_version=schemas["title"],
            provider=config.provider,
            endpoint=endpoint,
            model=config.model,
            text=job_input,
        )
        job_identities.append(identity)
        requested[identity] = job_input

    misses = {
        identity: text
        for identity, text in requested.items()
        if identity.key not in cache
    }
    if misses:
        fetched, _, _ = fetch_missing_embeddings(
            _embedding_client(config),
            config.model,
            misses,
            batch_size=config.embedding_batch_size,
        )
        cache.update(fetched)
        config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with config.cache_path.open("a", encoding="utf-8") as cache_file:
            for identity in misses:
                cache_file.write(
                    json.dumps(_cache_entry(identity, fetched[identity.key])) + "\n"
                )

    scores = pool_scores(
        [cache[identity.key] for identity in job_identities],
        [cache[identity.key] for identity in reference_identities],
        "mean" if config.reference_mode == "keyword-mean" else "max",
    )
    ranked = rank_by_scores(postings, scores, {})
    drop_count = int(config.cut_depth * len(jobs))
    posting_indices = {id(posting): index for index, posting in enumerate(postings)}
    dropped_indices = (
        {posting_indices[id(item.posting)] for item in ranked[-drop_count:]}
        if drop_count
        else set()
    )
    return [job for index, job in enumerate(jobs) if index not in dropped_indices]


def _load_policies(run_dir: Path) -> UserPolicies:
    """Read ``policies.yml`` for the run, validated through UserPolicies.

    Missing file means the planner skipped writing policies (defensive — the
    planner always writes it, even if empty), which we treat as permissive.
    """
    policies_path = run_dir / "policies.yml"
    if not policies_path.exists():
        return UserPolicies()
    payload = yaml.safe_load(policies_path.read_text()) or {}
    return UserPolicies.model_validate(payload)


def _resolve_user_email(conn: psycopg.Connection, user_id: Any) -> str:
    row = conn.execute(
        "SELECT email FROM app.users WHERE id = %s", (str(user_id),)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"app.users row missing for id={user_id}")
    return row[0]


def _persist(jobs: list[dict[str, Any]], dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job) + "\n")
    return len(jobs)


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


def process_job(
    conn: psycopg.Connection,
    job: dict[str, Any],
    *,
    runs_dir: Path,
    scrape_fn: ScrapeFn,
) -> int:
    """Run one claimed job end-to-end. Returns the post-policy posting count.

    Exceptions inside this function bubble up — :func:`run_worker` catches
    them at the boundary and stamps ``mark_failed``."""
    email = _resolve_user_email(conn, job["user_id"])
    run_dir = run_user_dir(runs_dir, job["run_id"], email)
    policies = _load_policies(run_dir)

    raw_jobs = list(scrape_fn(job["source"], job["query_payload"], conn))
    job_dicts = [_to_dict(j) for j in raw_jobs]
    filtered = _apply_title_filter(job_dicts, policies.prefilter.excluded_title_terms)
    title_filtered_count = len(filtered)
    veto_depth: float | None = None
    if job["source"] == "companies":
        veto_config = _load_embedding_veto_config(policies)
        if veto_config.enabled:
            filtered = _apply_embedding_veto(
                filtered,
                reference_text=_load_reference_texts(
                    run_dir, veto_config.reference_mode
                ),
                config=veto_config,
                cache=_load_embedding_cache(veto_config.cache_path),
            )
            veto_depth = veto_config.cut_depth

    dest = run_dir / "scrape" / f"{job['source']}.jsonl"
    count = _persist(filtered, dest)
    if veto_depth is None:
        log.info(
            "%s/%s — scraped %d, kept %d after title filter → %s",
            email,
            job["source"],
            len(job_dicts),
            title_filtered_count,
            dest,
        )
    else:
        log.info(
            "%s/%s — scraped %d, kept %d after title filter, kept %d after "
            "embedding veto (dropped %d, depth=%s) → %s",
            email,
            job["source"],
            len(job_dicts),
            title_filtered_count,
            count,
            title_filtered_count - count,
            veto_depth,
            dest,
        )
    return count


def run_worker(
    conn: psycopg.Connection,
    *,
    runs_dir: Path,
    scrape_fn: ScrapeFn = default_scrape_fn,
) -> dict[str, int]:
    """Claim-and-process loop. Returns ``{"succeeded": N, "failed": M}``.

    Loops until :func:`claim_next` returns ``None``. With single-process
    workers and source-serialization, that signals either "no pending rows"
    or "all pending rows blocked by a running sibling" — in single-process
    mode the second can't happen because the only running rows we'd be
    blocked by are ones we already finished. So None == done.

    Per CLAUDE.md ("fail fast, but log well"): the per-job try/except
    captures ``traceback.format_exc()`` into ``pipe.scrape_jobs.error`` and
    moves on. The exception is also logged so it surfaces in stderr right
    away, not just at end-of-run.
    """
    counters = {"succeeded": 0, "failed": 0}
    while True:
        job = claim_next(conn)
        if job is None:
            break
        try:
            count = process_job(conn, job, runs_dir=runs_dir, scrape_fn=scrape_fn)
            mark_succeeded(conn, job_id=job["id"], posting_count=count)
            counters["succeeded"] += 1
        except Exception:
            tb = traceback.format_exc()
            log.error(
                "Job %s (%s/%s) failed:\n%s",
                job["id"],
                job["user_id"],
                job["source"],
                tb,
            )
            mark_failed(conn, job_id=job["id"], error=tb)
            counters["failed"] += 1

    log.info(
        "Worker done: succeeded=%d failed=%d",
        counters["succeeded"],
        counters["failed"],
    )
    return counters
