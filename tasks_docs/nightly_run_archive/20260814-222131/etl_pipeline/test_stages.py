import pytest

from errors import RateLimitExceeded, RetryExhausted, StageFailure
from stages import BatchSink, FilterStage, RateLimitStage, RetryStage, Stage, TransformStage


class FakeClock:
    def __init__(self):
        self.time = 0.0
        self.sleeps = []

    def now(self):
        return self.time

    def sleep(self, secs):
        self.sleeps.append(secs)
        self.time += secs


class FlakyStage(Stage):
    def __init__(self, fail_before_success, name=None):
        super().__init__(name)
        self.fail_before_success = fail_before_success
        self.calls = 0

    def run(self, rows):
        self.calls += 1
        if self.calls <= self.fail_before_success:
            raise StageFailure(self.name, "transient boom")
        return rows


class ExplodingStage(Stage):
    def __init__(self, name=None):
        super().__init__(name)
        self.calls = 0

    def run(self, rows):
        self.calls += 1
        raise ValueError("hard error")


def test_transform_stage():
    stage = TransformStage(lambda rows: [r * 2 for r in rows])
    assert stage.run([1, 2, 3]) == [2, 4, 6]


def test_transform_stage_requires_callable():
    with pytest.raises(TypeError):
        TransformStage("not callable")


def test_filter_stage():
    stage = FilterStage(lambda r: r % 2 == 0)
    assert stage.run([1, 2, 3, 4]) == [2, 4]


def test_filter_stage_requires_callable():
    with pytest.raises(TypeError):
        FilterStage("not callable")


def test_retry_succeeds_after_two_failures():
    clock = FakeClock()
    inner = FlakyStage(fail_before_success=2)
    stage = RetryStage(inner, retries=2, backoff_base=0.1, sleep=clock.sleep)
    assert stage.run([1, 2, 3]) == [1, 2, 3]
    assert inner.calls == 3
    assert clock.sleeps == [0.1, 0.2]


def test_retry_exhausted_carries_last_error():
    clock = FakeClock()
    inner = FlakyStage(fail_before_success=99)
    stage = RetryStage(inner, retries=2, backoff_base=0.1, sleep=clock.sleep)
    with pytest.raises(RetryExhausted) as excinfo:
        stage.run([1])
    assert excinfo.value.attempts == 3
    assert isinstance(excinfo.value.last_error, StageFailure)
    assert clock.sleeps == [0.1, 0.2]


def test_retry_zero_retries():
    inner = FlakyStage(fail_before_success=1)
    stage = RetryStage(inner, retries=0, backoff_base=0.1, sleep=FakeClock().sleep)
    with pytest.raises(RetryExhausted):
        stage.run([1])
    assert inner.calls == 1


def test_retry_does_not_retry_non_retryable():
    clock = FakeClock()
    inner = ExplodingStage()
    stage = RetryStage(inner, retries=3, backoff_base=0.1, sleep=clock.sleep)
    with pytest.raises(StageFailure) as excinfo:
        stage.run([1])
    assert inner.calls == 1
    assert clock.sleeps == []
    assert isinstance(excinfo.value.cause, ValueError)


def test_retry_validates_arguments():
    inner = TransformStage(lambda rows: rows)
    with pytest.raises(ValueError):
        RetryStage(inner, retries=-1, backoff_base=0.1)
    with pytest.raises(ValueError):
        RetryStage(inner, retries=2, backoff_base=-1)
    with pytest.raises(TypeError):
        RetryStage("not a stage", retries=2, backoff_base=0.1)


def test_rate_limit_wait_keeps_sustained_rate():
    clock = FakeClock()
    stage = RateLimitStage(per_sec=5, now=clock.now, sleep=clock.sleep)
    out = stage.run(list(range(20)))
    assert len(out) == 20
    assert clock.time >= (20 - stage.burst) / stage.per_sec


def test_rate_limit_default_burst_is_one_second():
    stage = RateLimitStage(per_sec=5, now=FakeClock().now, sleep=FakeClock().sleep)
    assert stage.burst == 5


def test_rate_limit_burst_one_stricter():
    clock = FakeClock()
    stage = RateLimitStage(per_sec=5, burst=1, now=clock.now, sleep=clock.sleep)
    out = stage.run(list(range(20)))
    assert len(out) == 20
    assert clock.time >= 3.8


def test_rate_limit_raise_mode():
    clock = FakeClock()
    stage = RateLimitStage(per_sec=5, burst=5, on_limit="raise", now=clock.now,
                           sleep=clock.sleep)
    with pytest.raises(RateLimitExceeded):
        stage.run(list(range(20)))
    assert clock.sleeps == []


def test_rate_limit_validates_arguments():
    clock = FakeClock()
    with pytest.raises(ValueError):
        RateLimitStage(per_sec=0, now=clock.now, sleep=clock.sleep)
    with pytest.raises(ValueError):
        RateLimitStage(per_sec=5, burst=0, now=clock.now, sleep=clock.sleep)
    with pytest.raises(ValueError):
        RateLimitStage(per_sec=5, on_limit="bogus", now=clock.now, sleep=clock.sleep)


def test_batch_sink_flushes_on_limit():
    sink = BatchSink(limit=3)
    sink.run([1, 2])
    assert sink.data == []
    assert sink.pending == [1, 2]
    sink.run([3])
    assert sink.data == [1, 2, 3]
    assert sink.pending == []
    moved = sink.flush()
    assert moved == 0
    assert sink.data == [1, 2, 3]


def test_batch_sink_flush_is_idempotent():
    sink = BatchSink(limit=2)
    sink.run([1, 2, 3])
    sink.flush()
    before = list(sink.data)
    assert sink.flush() == 0
    assert sink.data == before


def test_batch_sink_empty_flush_is_noop():
    sink = BatchSink(limit=2)
    assert sink.flush() == 0
    assert sink.data == []


def test_batch_sink_limit_one_flushes_each():
    sink = BatchSink(limit=1)
    sink.run([1])
    assert sink.data == [1]
    sink.run([2])
    assert sink.data == [1, 2]


def test_batch_sink_run_returns_empty():
    sink = BatchSink(limit=2)
    assert sink.run([1, 2]) == []


def test_batch_sink_validates_limit():
    with pytest.raises(ValueError):
        BatchSink(limit=0)
