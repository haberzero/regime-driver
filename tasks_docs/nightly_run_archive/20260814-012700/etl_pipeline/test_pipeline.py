import pytest

from errors import InvalidPipelineError, StageFailure
from pipeline import Pipeline
from stages import (
    BatchSink,
    FilterStage,
    RetryStage,
    TransformStage,
)


# ---------------------------------------------------------------- naming

def test_auto_naming_is_sequential_and_idempotent():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="explicit"))
    p.add(TransformStage(lambda rows: rows))
    p.add(TransformStage(lambda rows: rows))
    assert p.stages[0].name == "explicit"
    assert p.stages[1].name == "stage_2"
    assert p.stages[2].name == "stage_3"
    p.validate()
    assert p.stages[1].name == "stage_2"
    assert p.stages[2].name == "stage_3"


# ---------------------------------------------------------------- validation

def test_duplicate_stage_name_detected():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="X"))
    p.add(TransformStage(lambda rows: rows, name="X"))
    with pytest.raises(InvalidPipelineError):
        p.validate()


def test_invalid_connection_detected():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="A"), depends_on="ghost")
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "ghost" in str(excinfo.value)


def test_cycle_a_b_a_detected_and_reported():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="A"))
    p.add(TransformStage(lambda rows: rows, name="B"), depends_on="A")
    p.connect("A", "B")  # A now depends on B -> A -> B -> A
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "cycle" in str(excinfo.value).lower()
    assert "A" in str(excinfo.value)
    assert "B" in str(excinfo.value)


def test_self_cycle_detected():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="A"), depends_on="A")
    with pytest.raises(InvalidPipelineError):
        p.validate()


def test_run_validates_cyclic_pipeline():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="A"))
    p.add(TransformStage(lambda rows: rows, name="B"), depends_on="A")
    p.connect("A", "B")
    with pytest.raises(InvalidPipelineError):
        p.run([1])


# ---------------------------------------------------------------- run / stats

def test_run_returns_processed_and_stage_stats():
    p = Pipeline()
    p.add(TransformStage(lambda rows: [r * 2 for r in rows], name="t"))
    p.add(FilterStage(lambda r: r > 4, name="f"))
    res = p.run([1, 2, 3, 4, 5])
    assert res["failed"] == 0
    assert res["processed"] == 10
    assert res["stage_stats"]["t"] == {"processed": 5, "failed": 0}
    assert res["stage_stats"]["f"] == {"processed": 5, "failed": 0}


def test_run_empty_and_single_row():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="t"))
    assert p.run([]) == {
        "processed": 0,
        "failed": 0,
        "stage_stats": {"t": {"processed": 0, "failed": 0}},
    }
    res = p.run([7])
    assert res["processed"] == 1
    assert res["stage_stats"]["t"]["processed"] == 1


def test_isolation_default_continues_after_failure():
    def boom(rows):
        raise RuntimeError("middle stage failed")

    sink = BatchSink(limit=100, name="sink")
    p = Pipeline()
    p.add(TransformStage(lambda rows: [r + 1 for r in rows], name="t"))
    p.add(TransformStage(boom, name="bomb"))
    p.add(sink)
    res = p.run([1, 2, 3])
    assert res["stage_stats"]["t"]["processed"] == 3
    assert res["stage_stats"]["bomb"]["failed"] == 3
    assert res["stage_stats"]["sink"]["processed"] == 0
    assert res["failed"] == 3
    assert res["processed"] == 3
    assert sink.rows == []  # nothing reached the sink


def test_fail_fast_raises_stage_failure():
    def boom(rows):
        raise RuntimeError("boom")

    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="t"))
    p.add(TransformStage(boom, name="bomb"))
    with pytest.raises(StageFailure) as excinfo:
        p.run([1, 2], fail_fast=True)
    assert excinfo.value.stage_name == "bomb"
    assert isinstance(excinfo.value.cause, RuntimeError)


# ---------------------------------------------------------------- integration

def test_retry_stage_in_pipeline_succeeds():
    calls = {"n": 0}

    def flaky(rows):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return rows

    sink = BatchSink(limit=100, name="sink")
    p = Pipeline()
    p.add(TransformStage(lambda rows: [r * 10 for r in rows], name="t"))
    p.add(
        RetryStage(
            TransformStage(flaky, name="inner"),
            retries=2,
            backoff_base=0.001,
            sleep_fn=lambda _s: None,
            name="retry",
        )
    )
    p.add(sink)
    res = p.run([1, 2])
    assert res["failed"] == 0
    assert sink.flush() == 2
    assert sink.rows == [10, 20]


def test_retry_exhaustion_is_isolated_in_pipeline():
    def always_fails(rows):
        raise ValueError("nope")

    sink = BatchSink(limit=100, name="sink")
    p = Pipeline()
    p.add(
        RetryStage(
            TransformStage(always_fails, name="inner"),
            retries=1,
            backoff_base=0.001,
            sleep_fn=lambda _s: None,
            name="r",
        )
    )
    p.add(sink)
    res = p.run([1, 2, 3])
    assert res["stage_stats"]["r"]["failed"] == 3
    assert res["failed"] == 3
    assert res["processed"] == 0
    assert sink.rows == []


def test_rate_limit_stage_in_pipeline():
    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    from stages import RateLimitStage

    rl = RateLimitStage(per_sec=5, burst=5, clock=FakeClock(), name="rl")
    sink = BatchSink(limit=100, name="sink")
    p = Pipeline()
    p.add(rl)
    p.add(sink)
    res = p.run(list(range(20)))
    assert res["failed"] == 0
    assert len(rl.consumed_at) == 20
    assert sink.flush() == 20
    assert sink.rows == list(range(20))
