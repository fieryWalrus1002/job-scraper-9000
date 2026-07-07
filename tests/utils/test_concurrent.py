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
    """An exception in one item propagates; queued futures are cancelled.

    Timing is the definitive proof: without cancel_futures=True, shutdown(wait=True)
    blocks until remaining items complete their 0.1s sleep (~0.8s for items 2-9).
    With cancellation the test exits in well under 0.5s even if one extra item
    races in before shutdown fires (a genuine race with max_workers=1).
    """
    started = []
    lock = threading.Lock()

    def slow_work(x: int):
        with lock:
            started.append(x)
        if x == 1:
            raise ValueError("boom")
        time.sleep(0.1)  # long enough to make cancellation detectable via timing
        return x

    items = list(range(10))
    t0 = time.monotonic()
    with pytest.raises(ValueError, match="boom"):
        for _ in imap_unordered(slow_work, items, max_workers=1):
            pass
    elapsed = time.monotonic() - t0

    # Without cancel_futures=True, shutdown would block ~0.8s for items 2–9.
    # With cancellation, wall time is dominated by item 0's sleep (0.1s).
    assert elapsed < 0.5, (
        f"Took {elapsed:.2f}s — queued futures may not have been cancelled"
    )
    with lock:
        assert len(started) < len(items), (
            f"Expected far fewer than {len(items)} items to run, got {started}"
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
