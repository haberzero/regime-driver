import threading
import time

import pytest

from limiter import TokenBucket


class FakeClock:
    def __init__(self, start=0.0):
        self._time = start

    def __call__(self):
        return self._time

    def advance(self, seconds):
        self._time += seconds


def test_initial_tokens_exhausted():
    bucket = TokenBucket(capacity=3, refill_rate=0)
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_refill_by_rate_injected_clock():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=10, refill_rate=2.0, clock=clock)
    for _ in range(10):
        assert bucket.allow() is True
    assert bucket.allow() is False

    clock.advance(1.0)
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_refill_rate_zero_no_auto_refill():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=2, refill_rate=0, clock=clock)
    assert bucket.allow() is True
    assert bucket.allow() is True
    clock.advance(100.0)
    assert bucket.allow() is False


def test_burst_does_not_exceed_capacity():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=5, refill_rate=1.0, clock=clock)
    clock.advance(10_000.0)
    allowed = sum(1 for _ in range(100) if bucket.allow())
    assert allowed == 5


def test_refill_caps_at_capacity():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=4, refill_rate=3.0, clock=clock)
    assert bucket.allow() is True
    clock.advance(100.0)
    allowed = sum(1 for _ in range(20) if bucket.allow())
    assert allowed == 4


def test_partial_refill_accumulates():
    clock = FakeClock(0.0)
    bucket = TokenBucket(capacity=1, refill_rate=0.5, clock=clock)
    assert bucket.allow() is True
    clock.advance(1.0)
    assert bucket.allow() is False
    clock.advance(2.0)
    assert bucket.allow() is True
    clock.advance(2.0)
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_stats_counts():
    bucket = TokenBucket(capacity=2, refill_rate=0)
    assert bucket.total_allowed == 0
    assert bucket.total_denied == 0
    assert bucket.stats() == {"total_allowed": 0, "total_denied": 0}

    bucket.allow()
    bucket.allow()
    bucket.allow()

    assert bucket.total_allowed == 2
    assert bucket.total_denied == 1
    assert bucket.stats() == {"total_allowed": 2, "total_denied": 1}


def test_invalid_capacity_raises():
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(capacity=0, refill_rate=1.0)
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(capacity=-1, refill_rate=1.0)


def test_invalid_refill_rate_raises():
    with pytest.raises(ValueError, match="refill_rate"):
        TokenBucket(capacity=1, refill_rate=-1)


def test_concurrent_no_overselling():
    capacity = 10
    refill_rate = 1000.0
    duration = 0.05
    num_threads = 8
    bucket = TokenBucket(capacity=capacity, refill_rate=refill_rate)

    stop = time.monotonic() + duration

    def worker():
        while time.monotonic() < stop:
            bucket.allow()

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    elapsed = time.monotonic() - (stop - duration)
    upper_bound = capacity + refill_rate * elapsed + 1
    assert bucket.total_allowed <= upper_bound
