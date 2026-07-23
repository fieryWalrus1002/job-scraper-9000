#!/usr/bin/env python3
"""Rank a companies-board scrape with cached embedding similarity.

This is a single-process prototype. Its JSONL cache is append-only and concurrent cache
writers are unsupported; use one process per cache file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import yaml

from agents.skills_fit.utils import _get_client
from src.prefilter.embedding import (
    CacheIdentity,
    Posting,
    RankedPosting,
    SCHEMAS_BY_PREFIX_SCHEME,
    TITLE_DESCRIPTION_SCHEMA,  # noqa: F401
    TITLE_SCHEMA,  # noqa: F401
    VARIANT_SCHEMAS,
    _cache_entry,
    _mean_or_none,
    apply_prefix_scheme,
    build_job_text,
    build_keywords_reference_text,
    build_per_keyword_reference_texts,
    build_reference_text,
    build_skills_reference_text,
    cache_identity,
    cosine_similarity,  # noqa: F401
    endpoint_identity,
    fetch_missing_embeddings,
    parse_cache_jsonl,
    parse_postings_jsonl,
    parse_skills_fit_jsonl,
    pool_scores,
    rank_by_scores,
    sha256_text,
    validate_profile,
)

log = logging.getLogger(__name__)

OUTPUT_FILES = {
    "title": "ranked_title.csv",
    "title_description_500": "ranked_title_description_500.csv",
    "manifest": "manifest.json",
}
CSV_COLUMNS = [
    "variant",
    "global_rank",
    "company_rank",
    "similarity",
    "company",
    "title",
    "source_url",
    "dedup_hash",
    "description_fallback",
    "ai_fit",
]
EMBEDDING_BATCH_SIZE = 100


def rank_postings(
    postings: Sequence[Posting],
    vectors: Sequence[Sequence[float]],
    reference_vector: Sequence[float],
    ai_fits: dict[str, int | None],
) -> list[RankedPosting]:
    """Legacy single-reference entry point — delegates to pool_scores + rank_by_scores."""
    scores = pool_scores(vectors, [reference_vector], "max")
    return rank_by_scores(postings, scores, ai_fits)


def ai_fit_rank_summary(
    ranked: Sequence[RankedPosting],
) -> dict[str, dict[str, float | None]]:
    summary: dict[str, dict[str, float | None]] = {}
    for rank in (25, 50, 100):
        if len(ranked) >= rank:
            summary[f"top_{rank}_vs_rest"] = {
                "top_mean": _mean_or_none(item.ai_fit for item in ranked[:rank]),
                "rest_mean": _mean_or_none(item.ai_fit for item in ranked[rank:]),
            }
    return summary


def _log_rank_checkpoints(variant: str, ranked: Sequence[RankedPosting]) -> None:
    per_company: defaultdict[str, list[RankedPosting]] = defaultdict(list)
    for item in ranked:
        per_company[item.posting.company].append(item)
    for company, company_ranked in sorted(per_company.items()):
        log.info(
            "variant=%s company=%s posting_count=%d",
            variant,
            company,
            len(company_ranked),
        )
        for position in (25, 50, 100):
            if len(company_ranked) >= position:
                log.info(
                    "variant=%s company=%s company_rank=%d similarity=%.8f",
                    variant,
                    company,
                    position,
                    company_ranked[position - 1].similarity,
                )


def _csv_bytes(variant: str, ranked: Sequence[RankedPosting]) -> bytes:
    rows: list[dict[str, object]] = []
    for item in ranked:
        rows.append(
            {
                "variant": variant,
                "global_rank": item.global_rank,
                "company_rank": item.company_rank,
                "similarity": f"{item.similarity:.12f}",
                "company": item.posting.company,
                "title": item.posting.title,
                "source_url": item.posting.source_url,
                "dedup_hash": item.posting.dedup_hash,
                "description_fallback": str(item.posting.description_fallback).lower(),
                "ai_fit": "" if item.ai_fit is None else item.ai_fit,
            }
        )
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def validate_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Output directory {output_dir} is non-empty; pass --overwrite to replace prototype output"
        )


def publish_outputs(
    output_dir: Path,
    rendered_outputs: dict[str, bytes],
    *,
    overwrite: bool,
) -> None:
    """Publish all output files with temp files followed by atomic renames."""
    validate_output_dir(output_dir, overwrite=overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    published: set[str] = set()
    try:
        for filename, content in rendered_outputs.items():
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=output_dir, prefix=f".{filename}.", delete=False
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_paths[filename] = Path(temporary.name)
        for filename in rendered_outputs:
            destination = output_dir / filename
            if destination.exists():
                backup = output_dir / f".{filename}.backup"
                os.replace(destination, backup)
                backups[filename] = backup
        for filename, temporary_path in temporary_paths.items():
            os.replace(temporary_path, output_dir / filename)
            published.add(filename)
    except Exception:
        for filename in rendered_outputs:
            destination = output_dir / filename
            backup = backups.get(filename)
            if filename in published:
                destination.unlink(missing_ok=True)
            if backup is not None and backup.exists():
                os.replace(backup, destination)
        raise
    finally:
        for temporary_path in temporary_paths.values():
            temporary_path.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def parse_variants(value: str) -> list[str]:
    variants = [part.strip() for part in value.split(",") if part.strip()]
    if not variants:
        raise ValueError("--job-text-variants must name at least one variant")
    invalid = set(variants) - VARIANT_SCHEMAS.keys()
    if invalid:
        raise ValueError(
            "--job-text-variants accepts only title,title_description_500; got "
            + ", ".join(sorted(invalid))
        )
    if len(set(variants)) != len(variants):
        raise ValueError("--job-text-variants may not repeat a variant")
    return variants


def run(
    args: argparse.Namespace, *, embedding_client: Any | None = None
) -> dict[str, object]:
    """CLI orchestration; ``embedding_client`` exists only for offline tests."""
    input_path = Path(args.input)
    profile_path = Path(args.profile)
    cache_path = Path(args.cache)
    output_dir = Path(args.output_dir)
    if args.provider == "openai" and args.base_url:
        raise ValueError("--base-url is valid only for ollama")
    if args.provider == "openai" and not os.environ.get(args.api_key_env):
        raise RuntimeError(f"{args.api_key_env} is not set in environment")
    validate_output_dir(output_dir, overwrite=args.overwrite)
    base_url = (
        args.base_url
        if args.provider == "ollama" and args.base_url
        else os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    )
    endpoint = endpoint_identity(
        args.provider, base_url if args.provider == "ollama" else None
    )
    variants = parse_variants(args.job_text_variants)
    embedding_batch_size = getattr(args, "embedding_batch_size", EMBEDDING_BATCH_SIZE)
    if args.prefix_scheme not in SCHEMAS_BY_PREFIX_SCHEME:
        raise ValueError(f"Unknown prefix scheme: {args.prefix_scheme}")
    schemas = SCHEMAS_BY_PREFIX_SCHEME[args.prefix_scheme]
    log.info("prefix_scheme=%s", args.prefix_scheme)

    try:
        postings = parse_postings_jsonl(
            input_path.read_text(encoding="utf-8"), input_path
        )
    except OSError as exc:
        raise OSError(f"Could not read input {input_path}: {exc}") from exc
    try:
        profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load profile {profile_path}: {exc}") from exc
    profile = validate_profile(profile_data, profile_path)
    try:
        cache = parse_cache_jsonl(cache_path.read_text(encoding="utf-8"), cache_path)
    except FileNotFoundError:
        cache = {}
    except OSError as exc:
        raise OSError(f"Could not read cache {cache_path}: {exc}") from exc

    ai_fits: dict[str, int | None] = {}
    skills_fit_path: Path | None = Path(args.skills_fit) if args.skills_fit else None
    if skills_fit_path is not None:
        try:
            ai_fits = parse_skills_fit_jsonl(
                skills_fit_path.read_text(encoding="utf-8"), skills_fit_path
            )
        except OSError as exc:
            raise OSError(
                f"Could not read skills-fit input {skills_fit_path}: {exc}"
            ) from exc

    # --- Build reference texts for the selected mode ---
    reference_mode = args.reference_mode
    if reference_mode == "blend":
        reference_texts = [
            build_reference_text(profile, args.target_title, args.goal_summary)
        ]
    elif reference_mode == "keywords":
        reference_texts = [build_keywords_reference_text(args.target_title)]
    elif reference_mode in ("keyword-max", "keyword-mean"):
        reference_texts = build_per_keyword_reference_texts(args.target_title)
    elif reference_mode == "skills-max":
        reference_texts = build_per_keyword_reference_texts(args.target_title) + [
            build_skills_reference_text(profile)
        ]
    elif reference_mode == "exemplar":
        if not args.allow_ground_truth_reference:
            raise ValueError("exemplar mode requires --allow-ground-truth-reference")
        if skills_fit_path is None:
            raise ValueError(
                "exemplar mode requires --skills-fit with ai_fit ground truth"
            )
        reference_texts = []  # resolved from job vectors later; no new embeddings
    else:
        raise ValueError(f"Unknown reference mode: {reference_mode!r}")

    # Build prefixed reference texts + cache identities (exemplar skips this)
    requested: dict[CacheIdentity, str] = {}
    reference_identities: list[CacheIdentity] = []
    if reference_mode != "exemplar":
        for rtext in reference_texts:
            prefixed = apply_prefix_scheme(
                rtext, role="reference", prefix_scheme=args.prefix_scheme
            )
            rid = cache_identity(
                schema_version=schemas["reference"],
                provider=args.provider,
                endpoint=endpoint,
                model=args.model,
                text=prefixed,
            )
            requested[rid] = prefixed
            reference_identities.append(rid)
    job_identities: dict[str, list[CacheIdentity]] = {
        variant: [] for variant in variants
    }
    fallback_count = sum(posting.description_fallback for posting in postings)
    for variant in variants:
        for posting in postings:
            text = apply_prefix_scheme(
                build_job_text(posting, variant),
                role="job",
                prefix_scheme=args.prefix_scheme,
            )
            identity = cache_identity(
                schema_version=schemas[variant],
                provider=args.provider,
                endpoint=endpoint,
                model=args.model,
                text=text,
            )
            requested[identity] = text
            job_identities[variant].append(identity)

    misses = {
        identity: text
        for identity, text in requested.items()
        if identity.key not in cache
    }
    hits = len(requested) - len(misses)
    if misses:
        if embedding_client is None:
            config: dict[str, str] = {
                "provider": args.provider,
                "model": args.model,
                "api_key_env": args.api_key_env,
            }
            if args.provider == "ollama":
                config["base_url"] = endpoint
            embedding_client, configured_model = _get_client(config)
            if configured_model != args.model:
                raise RuntimeError(
                    "Embedding client returned an unexpected configured model"
                )
        fetched, vectors_requested, api_batches = fetch_missing_embeddings(
            embedding_client,
            args.model,
            misses,
            batch_size=embedding_batch_size,
        )
        cache.update(fetched)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a", encoding="utf-8") as cache_file:
            for identity in misses:
                cache_file.write(
                    json.dumps(
                        _cache_entry(identity, fetched[identity.key]),
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    else:
        vectors_requested = 0
        api_batches = 0

    # Determine pool reduction for the mode
    if reference_mode == "keyword-mean":
        pool = "mean"
    else:
        pool = "max"

    rankings: dict[str, list[RankedPosting]] = {}
    variant_cache_statistics: dict[str, dict[str, int]] = {}
    for variant in variants:
        job_vecs = [cache[identity.key] for identity in job_identities[variant]]

        # --- Build reference vectors for this variant ---
        if reference_mode == "exemplar":
            # Centroid from job vectors with ai_fit >= 4 (no new embeddings)
            good_vecs = [
                jvec
                for jvec, posting in zip(job_vecs, postings, strict=True)
                if (fit := ai_fits.get(posting.dedup_hash)) is not None and fit >= 4
            ]
            if not good_vecs:
                raise ValueError(
                    f"exemplar mode: no jobs with ai_fit >= 4 in variant {variant!r}"
                )
            dim = len(good_vecs[0])
            centroid = [
                sum(v[i] for v in good_vecs) / len(good_vecs) for i in range(dim)
            ]
            ref_vectors = [centroid]
        else:
            ref_vectors = [cache[rid.key] for rid in reference_identities]

        # Cache statistics for the variant
        variant_all_identities = [*reference_identities, *job_identities[variant]]
        variant_hits = sum(
            identity not in misses for identity in dict.fromkeys(variant_all_identities)
        )
        variant_misses = sum(
            identity in misses for identity in dict.fromkeys(variant_all_identities)
        )

        scores = pool_scores(job_vecs, ref_vectors, pool)
        ranked = rank_by_scores(postings, scores, ai_fits)
        rankings[variant] = ranked
        variant_cache_statistics[variant] = {
            "cache_hits": variant_hits,
            "cache_misses": variant_misses,
            "vectors_requested": variant_misses,
            "provider_api_batches": api_batches if variant_misses else 0,
        }
        log.info(
            "variant=%s cache_hits=%d cache_misses=%d vectors_requested=%d provider_api_batches=%d",
            variant,
            variant_hits,
            variant_misses,
            variant_misses,
            api_batches if variant_misses else 0,
        )
        _log_rank_checkpoints(variant, ranked)
        if skills_fit_path is not None:
            log.info(
                "variant=%s ai_fit_rank_summary=%s",
                variant,
                ai_fit_rank_summary(ranked),
            )

    matched_count = sum(
        posting.dedup_hash in ai_fits and ai_fits[posting.dedup_hash] is not None
        for posting in postings
    )
    unmatched_count = len(postings) - matched_count
    if skills_fit_path is not None:
        log.info("ranked postings without ai_fit match: %d", unmatched_count)
    log.info(
        "input_count=%d distinct_companies=%d blank_description_fallbacks=%d cache_hits=%d cache_misses=%d vectors_requested=%d provider_api_batches=%d",
        len(postings),
        len({posting.company for posting in postings}),
        fallback_count,
        hits,
        len(misses),
        vectors_requested,
        api_batches,
    )

    summaries = {
        variant: ai_fit_rank_summary(ranked) for variant, ranked in rankings.items()
    }
    manifest: dict[str, object] = {
        "cli_arguments": {
            "input": str(input_path),
            "profile": str(profile_path),
            "target_title": args.target_title,
            "goal_summary": args.goal_summary,
            "provider": args.provider,
            "model": args.model,
            "base_url": endpoint if args.provider == "ollama" else None,
            "api_key_env": args.api_key_env if args.provider == "openai" else None,
            "cache": str(cache_path),
            "output_dir": str(output_dir),
            "overwrite": args.overwrite,
            "embedding_batch_size": embedding_batch_size,
            "job_text_variants": variants,
            "prefix_scheme": args.prefix_scheme,
            "reference_mode": reference_mode,
            "reference_vector_count": len(reference_identities),
            "skills_fit": str(skills_fit_path) if skills_fit_path else None,
        },
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "input_count": len(postings),
        "company_counts": dict(
            sorted(Counter(posting.company for posting in postings).items())
        ),
        "blank_description_fallback_count": fallback_count,
        "reference_input_sha256": [sha256_text(rt) for rt in reference_texts],
        "cache_path": str(cache_path),
        "cache_statistics": {
            "cache_hits": hits,
            "cache_misses": len(misses),
            "vectors_requested": vectors_requested,
            "provider_api_batches": api_batches,
            "by_variant": variant_cache_statistics,
        },
        "output_filenames": [OUTPUT_FILES[variant] for variant in variants]
        + [OUTPUT_FILES["manifest"]],
        "text_builder_schema_versions": {
            "reference": schemas["reference"],
            **{variant: schemas[variant] for variant in variants},
        },
    }
    if skills_fit_path is not None:
        manifest["skills_fit"] = {
            "path": str(skills_fit_path),
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "mean_ai_fit_by_rank_band": summaries,
        }

    rendered = {
        OUTPUT_FILES[variant]: _csv_bytes(variant, rankings[variant])
        for variant in variants
    }
    rendered[OUTPUT_FILES["manifest"]] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    publish_outputs(output_dir, rendered, overwrite=args.overwrite)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Companies JSONL input")
    parser.add_argument(
        "--profile", required=True, help="Materialized candidate profile YAML"
    )
    parser.add_argument("--target-title", action="append", required=True)
    parser.add_argument("--goal-summary", default="")
    parser.add_argument("--provider", choices=("openai", "ollama"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument(
        "--cache", default="data/cache/companies_prefilter_embeddings.jsonl"
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=EMBEDDING_BATCH_SIZE,
        help="Embedding inputs per provider request (default: %(default)s)",
    )
    parser.add_argument("--job-text-variants", default="title,title_description_500")
    parser.add_argument("--prefix-scheme", choices=("none", "nomic"), default="none")
    parser.add_argument(
        "--reference-mode",
        choices=(
            "blend",
            "keywords",
            "keyword-max",
            "keyword-mean",
            "skills-max",
            "exemplar",
        ),
        default="blend",
        help="Similarity reference mode (default: blend)",
    )
    parser.add_argument(
        "--allow-ground-truth-reference",
        action="store_true",
        help="Allow exemplar mode which reads ai_fit ground truth",
    )
    parser.add_argument("--skills-fit")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    run(args)


if __name__ == "__main__":
    main()
