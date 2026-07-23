"""Pure embedding-similarity scoring and ranking helpers."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Sequence

from .models import Posting, RankedPosting


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError(
            "Cannot calculate cosine similarity for unequal vector dimensions"
        )
    if not left:
        raise ValueError("Cannot calculate cosine similarity for empty vectors")
    if not all(math.isfinite(value) for value in (*left, *right)):
        raise ValueError("Cannot calculate cosine similarity for non-finite vectors")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cannot calculate cosine similarity for zero-norm vectors")
    result = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    if not math.isfinite(result):
        raise ValueError("Cosine similarity was non-finite")
    return result


def pool_scores(
    job_vectors: Sequence[Sequence[float]],
    reference_vectors: Sequence[Sequence[float]],
    pool: str,
) -> list[float]:
    """Score each job against every reference vector and reduce by *pool*.

    *pool* is ``"max"`` or ``"mean"``. A single-reference mode passes a
    one-element *reference_vectors* list.
    """
    if not reference_vectors:
        raise ValueError("reference_vectors must not be empty")
    if pool not in ("max", "mean"):
        raise ValueError(f"Unknown pool mode: {pool!r}")
    scores: list[float] = []
    for jvec in job_vectors:
        sims = [cosine_similarity(jvec, rvec) for rvec in reference_vectors]
        if pool == "max":
            scores.append(max(sims))
        else:
            scores.append(sum(sims) / len(sims))
    return scores


def rank_by_scores(
    postings: Sequence[Posting],
    scores: list[float],
    ai_fits: dict[str, int | None],
) -> list[RankedPosting]:
    """Sort postings by precomputed *scores* (desc) and assign ranks."""
    if len(postings) != len(scores):
        raise ValueError("Posting/score count mismatch")
    scored = list(zip(postings, scores, strict=True))
    scored.sort(key=lambda item: (-item[1], item[0].dedup_hash))
    company_positions: defaultdict[str, int] = defaultdict(int)
    ranked: list[RankedPosting] = []
    for global_rank, (posting, similarity) in enumerate(scored, start=1):
        company_positions[posting.company] += 1
        ranked.append(
            RankedPosting(
                posting=posting,
                similarity=similarity,
                global_rank=global_rank,
                company_rank=company_positions[posting.company],
                ai_fit=ai_fits.get(posting.dedup_hash),
            )
        )
    return ranked
