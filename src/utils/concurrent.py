"""Small thread-pool helper for fanning blocking I/O (LLM calls) out concurrently.

The pipeline's LLM calls are ~seconds of network wait each and parallelize
near-linearly. This wraps ``ThreadPoolExecutor`` so callers keep all shared,
non-thread-safe state (caches, counters, run trackers, file handles) on the main
thread and only push the pure network call into the pool.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def imap_unordered(
    work: Callable[[T], R],
    items: Iterable[T],
    *,
    max_workers: int,
) -> Iterator[tuple[T, R]]:
    """Yield ``(item, work(item))`` pairs as they complete, unordered.

    Runs ``work`` across at most ``max_workers`` threads. Intended for blocking
    I/O (network); ``work`` should not touch shared mutable state — do that in the
    consuming loop on the main thread. Exceptions raised by ``work`` propagate from
    the corresponding ``next()`` (fail fast); remaining futures are cancelled and the
    pool is torn down. ``max_workers`` is clamped to at least 1.

    ``items`` is **eagerly materialized** before any work starts — all futures are
    submitted up front. Callers must pass a finite, bounded iterable; passing an
    infinite or very large generator will exhaust memory before the first result
    is yielded. This repo's job lists are always bounded, so that constraint holds.
    """
    materialized = list(items)
    if not materialized:
        return
    pool = ThreadPoolExecutor(max_workers=max(1, max_workers))
    try:
        future_to_item = {pool.submit(work, item): item for item in materialized}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            yield item, future.result()  # re-raises worker exception here
    finally:
        # cancel_futures is load-bearing: all items are submitted up front, so a
        # plain shutdown(wait=True) — what `with ThreadPoolExecutor` does — would
        # block until every QUEUED future ran to completion (for a 1349-job run,
        # potentially the better part of an hour of zombie API calls after a
        # failure or Ctrl-C). cancel_futures drops the queue; wait=True then only
        # drains the <= max_workers calls already in flight.
        pool.shutdown(wait=True, cancel_futures=True)
