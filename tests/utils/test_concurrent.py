import threading
import time

import pytest

from utils.concurrent import imap_unordered


def test_yields_all_items_exactly_once_with_correct_pairing():
    items = [10, 20, 30, 40, 50]
    results = list(imap_unordered(lambda x: x * 2, items, max_workers=3))

    assert len(results) == len(items)
    # Check pairing: each result matches work(item)
    paired = {item: result for item, result in results}
    for item in items:
        assert paired[item] == item * 2


def test_empty_input_yields_nothing():
    results = list(imap_unordered(lambda x: x, [], max_workers=2))
    assert results == []


def test_generator_input_is_materialized():
    """imap_unordered materializes the iterable once (submits all up front)."""
    results = list(
        imap_unordered(lambda x: x + 1, (i for i in range(3)), max_workers=2)
    )
    assert len(results) == 3
    paired = {item: result for item, result in results}
    assert paired == {0: 1, 1: 2, 2: 3}


def test_exception_propagates_and_cancels_queued_futures():
    """An exception in one item propagates; unstarted futures are cancelled."""
    started = []
    lock = threading.Lock()

    def slow_work(x: int):
        with lock:
            started.append(x)
        if x == 1:
            raise ValueError("boom")
        time.sleep(0.05)
        return x

    items = list(range(10))  # 10 items, but only 1 worker
    with pytest.raises(ValueError, match="boom"):
        for _ in imap_unordered(slow_work, items, max_workers=1):
            pass

    # With 1 worker, at most 1-2 items could have started (the one that raised
    # and possibly one already in flight). Far fewer than all 10.
    with lock:
        assert len(started) < len(items), (
            f"Expected cancellation, but {len(started)}/{len(items)} started"
        )


def test_concurrency_happens():
    """Wall-clock time proves multiple threads run in parallel."""
    n = 8
    sleep_time = 0.05  # 50ms per item

    def slow_work(x: int):
        time.sleep(sleep_time)
        return x

    start = time.monotonic()
    results = list(imap_unordered(slow_work, list(range(n)), max_workers=n))
    elapsed = time.monotonic() - start

    assert len(results) == n
    # With n workers and n items, wall time should be ~sleep_time, not n*sleep_time.
    # Use generous bound (0.6x of sequential) to avoid flakiness.
    sequential_time = n * sleep_time
    assert elapsed < sequential_time * 0.6, (
        f"Expected <{sequential_time * 0.6:.3f}s, got {elapsed:.3f}s — "
        "concurrency may not be working"
    )
