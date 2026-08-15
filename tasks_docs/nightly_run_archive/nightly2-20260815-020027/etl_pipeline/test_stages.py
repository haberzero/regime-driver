import pytest

from errors import RateLimitExceeded, RetryExhausted
from stages import BatchSink, FilterStage, RateLimitStage, RetryStage, TransformStage


def test_transform_stage_transforms_rows():
    stage = TransformStage(lambda rows: [row.upper() for row in rows])
    assert stage.run(["a", "b"]) == ["A", "B"]


def test_filter_stage_keeps_matching_rows():
    stage = FilterStage(lambda row: row % 2 == 0)
    assert stage.run([1, 2, 3, 4]) == [2, 4]


def test_retry_stage_succeeds_on_third_attempt():
    calls = {"n": 0}

    def flaky(rows):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return [row * 2 for row in rows]

    stage = RetryStage(TransformStage(flaky), retries=2, backoff_base=0.0)
    assert stage.run([1, 2]) == [2, 4]
    assert calls["n"] == 3


def test_retry_stage_exhausted_carries_last_error():
    def always_fail(rows):
        raise ValueError("boom")

    stage = RetryStage(TransformStage(always_fail), retries=2, backoff_base=0.0)
    with pytest.raises(RetryExhausted) as excinfo:
        stage.run([1])
    assert isinstance(excinfo.value.last_error, ValueError)
    assert str(excinfo.value.last_error) == "boom"
    assert excinfo.value.attempts == 3


def test_retry_stage_exponential_backoff():
    sleeps = []

    def always_fail(rows):
        raise ValueError("boom")

    stage = RetryStage(
        TransformStage(always_fail),
        retries=3,
        backoff_base=1.0,
        sleeper=sleeps.append,
    )
    with pytest.raises(RetryExhausted):
        stage.run([1])
    assert sleeps == [1.0, 2.0, 4.0]


def test_rate_limit_steady_state_with_injected_clock():
    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = FakeClock()
    stage = RateLimitStage(
        per_sec=5, capacity=5, clock=clock.time, sleeper=clock.sleep
    )

    times = []
    for value in range(20):
        stage.run([value])
        times.append(clock.now)

    assert times[0] == 0.0
    assert times[4] == 0.0
    assert times[5] == pytest.approx(0.2)
    assert times[19] == pytest.approx(3.0)
    for index in range(6, 20):
        assert times[index] - times[index - 1] == pytest.approx(0.2)


def test_rate_limit_raise_mode():
    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = FakeClock()
    stage = RateLimitStage(
        per_sec=5, capacity=5, on_overrun="raise",
        clock=clock.time, sleeper=clock.sleep,
    )
    with pytest.raises(RateLimitExceeded):
        stage.run(list(range(6)))


def test_batch_sink_auto_flush_and_manual_flush():
    sink = BatchSink(limit=3)
    assert sink.run([1, 2, 3, 4, 5]) == []
    assert sink.rows == [[1, 2, 3]]
    assert sink.buffered == 2
    sink.flush()
    assert sink.rows == [[1, 2, 3], [4, 5]]
    assert sink.buffered == 0


def test_batch_sink_flush_is_idempotent():
    sink = BatchSink(limit=10)
    sink.run([1, 2, 3])
    sink.flush()
    sink.flush()
    sink.flush()
    assert sink.rows == [[1, 2, 3]]
