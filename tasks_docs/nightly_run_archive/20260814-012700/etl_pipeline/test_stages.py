import pytest

from errors import RateLimitExceeded, RetryExhausted
from stages import (
    BatchSink,
    FilterStage,
    RateLimitStage,
    RetryStage,
    TransformStage,
)


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- transform/filter

def test_transform_stage_applies_fn():
    stage = TransformStage(lambda rows: [r * 2 for r in rows], name="t")
    assert stage.run([1, 2, 3]) == [2, 4, 6]


def test_filter_stage_keeps_matching_rows():
    stage = FilterStage(lambda r: r % 2 == 0, name="f")
    assert stage.run([1, 2, 3, 4, 5]) == [2, 4]


# ---------------------------------------------------------------- retry

def test_retry_stage_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(rows):
        calls["n"] += 1
        if calls["n"] < 3:  # 2 failures, then success
            raise ValueError("transient")
        return [r + 1 for r in rows]

    stage = RetryStage(
        TransformStage(flaky, name="inner"),
        retries=2,
        backoff_base=0.001,
        sleep_fn=lambda _s: None,
        name="retry",
    )
    assert stage.run([1, 2]) == [2, 3]
    assert calls["n"] == 3


def test_retry_stage_exhausted_raises_retry_exhausted():
    calls = {"n": 0}

    def always_fails(rows):
        calls["n"] += 1
        raise ValueError("boom")

    stage = RetryStage(
        TransformStage(always_fails, name="inner"),
        retries=2,
        backoff_base=0.001,
        sleep_fn=lambda _s: None,
        name="retry",
    )
    with pytest.raises(RetryExhausted) as excinfo:
        stage.run([1])
    assert isinstance(excinfo.value.last_error, ValueError)
    assert excinfo.value.attempts == 3
    assert calls["n"] == 3


def test_retry_backoff_is_exponential():
    sleeps = []

    def always_fails(rows):
        raise ValueError("always")

    stage = RetryStage(
        TransformStage(always_fails),
        retries=3,
        backoff_base=1.0,
        sleep_fn=sleeps.append,
    )
    with pytest.raises(RetryExhausted):
        stage.run([1])
    assert sleeps == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------- rate limit

def test_rate_limit_sustained_rate_stays_at_or_below_per_sec():
    clock = FakeClock()
    stage = RateLimitStage(per_sec=5, burst=5, clock=clock, name="rl")
    rows = list(range(20))
    assert stage.run(rows) == rows

    stamps = stage.consumed_at
    assert len(stamps) == 20
    # bounded burst: first 5 pass instantly
    assert stamps[0] == 0.0 and stamps[4] == 0.0
    # afterwards one token per 1/5 s
    intervals = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(i >= 0.2 - 1e-9 for i in intervals[4:])
    # total time is at least (N - burst) / per_sec
    assert stamps[-1] - stamps[0] >= (20 - 5) / 5.0 - 1e-9


def test_rate_limit_burst_is_bounded():
    clock = FakeClock()
    stage = RateLimitStage(per_sec=5, burst=2, clock=clock)
    stage.run(["a", "b", "c", "d"])
    stamps = stage.consumed_at
    assert stamps[:2] == [0.0, 0.0]
    assert abs(stamps[2] - 0.2) < 1e-9
    assert abs(stamps[3] - 0.4) < 1e-9


def test_rate_limit_raise_on_limit():
    clock = FakeClock()
    stage = RateLimitStage(per_sec=5, burst=2, raise_on_limit=True, clock=clock)
    stage.run(["a", "b"])  # consumes the burst
    with pytest.raises(RateLimitExceeded):
        stage.run(["c"])


# ---------------------------------------------------------------- validation

def test_stage_parameter_validation():
    with pytest.raises(TypeError):
        TransformStage(fn=None)
    with pytest.raises(TypeError):
        FilterStage(pred=None)
    with pytest.raises(TypeError):
        RetryStage(inner="not a stage", retries=1)
    with pytest.raises(ValueError):
        RetryStage(TransformStage(lambda r: r), retries=-1)
    with pytest.raises(ValueError):
        RetryStage(TransformStage(lambda r: r), retries=1, backoff_base=-0.1)
    with pytest.raises(ValueError):
        RateLimitStage(per_sec=0)
    with pytest.raises(ValueError):
        RateLimitStage(per_sec=5, burst=0)
    with pytest.raises(ValueError):
        BatchSink(limit=0)


def test_stages_handle_empty_batches():
    assert TransformStage(lambda r: [x * 2 for x in r]).run([]) == []
    assert FilterStage(lambda r: r > 0).run([]) == []
    assert (
        RetryStage(
            TransformStage(lambda r: r), retries=2, sleep_fn=lambda _s: None
        ).run([])
        == []
    )
    assert RateLimitStage(per_sec=5).run([]) == []


def test_retry_attempts_reported_per_run_not_cumulative():
    def always_fails(rows):
        raise ValueError("x")

    stage = RetryStage(
        TransformStage(always_fails), retries=1, sleep_fn=lambda _s: None
    )
    with pytest.raises(RetryExhausted) as first:
        stage.run([1])
    assert first.value.attempts == 2
    with pytest.raises(RetryExhausted) as second:
        stage.run([1])
    assert second.value.attempts == 2
    assert stage.attempts == 2


# ---------------------------------------------------------------- batch sink

def test_batch_sink_commits_full_batches_and_flushes_remainder():
    sink = BatchSink(limit=3, name="sink")
    sink.run([1, 2, 3, 4, 5])
    assert sink.rows == [1, 2, 3]
    assert sink.flush() == 2
    assert sink.rows == [1, 2, 3, 4, 5]


def test_batch_sink_flush_is_idempotent():
    sink = BatchSink(limit=2)
    sink.run([1, 2, 3])
    sink.flush()
    first = list(sink.rows)
    assert sink.flush() == 0
    assert sink.flush() == 0
    assert sink.rows == first
    assert len(sink.rows) == 3


def test_batch_sink_limit_one_commits_immediately():
    sink = BatchSink(limit=1)
    sink.run([1, 2, 3])
    assert sink.rows == [1, 2, 3]
    assert sink.flush() == 0


def test_batch_sink_single_row_buffered_until_flush():
    sink = BatchSink(limit=10)
    sink.run([42])
    assert sink.rows == []
    assert sink.flush() == 1
    assert sink.rows == [42]
    assert sink.flush() == 0
