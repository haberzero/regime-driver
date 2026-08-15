import pytest

from errors import InvalidPipelineError, StageFailure
from pipeline import Pipeline
from stages import BatchSink, FilterStage, Stage, TransformStage


class BoomStage(Stage):
    def run(self, rows):
        raise ValueError("boom")


class CountStage(Stage):
    def __init__(self, name=None):
        super().__init__(name)
        self.calls = 0

    def run(self, rows):
        self.calls += 1
        return rows


def test_add_assigns_names_by_sequence():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows))
    p.add(TransformStage(lambda rows: rows))
    assert [s.name for s in p.stages] == ["stage_1", "stage_2"]


def test_add_same_stage_object_is_noop():
    p = Pipeline()
    stage = TransformStage(lambda rows: rows)
    p.add(stage)
    p.add(stage)
    assert len(p.stages) == 1


def test_add_returns_self_for_chaining():
    p = Pipeline()
    assert p.add(TransformStage(lambda rows: rows)) is p


def test_run_returns_contract_dict():
    p = Pipeline()
    p.add(TransformStage(lambda rows: [r + 1 for r in rows]))
    result = p.run([1, 2, 3])
    assert set(result) == {"processed", "failed", "stage_stats"}
    assert result["processed"] == 3
    assert result["failed"] == 0
    assert result["stage_stats"]["stage_1"]["in"] == 3
    assert result["stage_stats"]["stage_1"]["out"] == 3


def test_run_filter_and_sink():
    sink = BatchSink(limit=2)
    p = Pipeline()
    p.add(FilterStage(lambda r: r % 2 == 0))
    p.add(sink)
    result = p.run([1, 2, 3, 4, 5])
    assert result["processed"] == 5
    assert result["failed"] == 0
    assert sink.data == [2, 4]


def test_run_empty_input():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows))
    result = p.run([])
    assert result["processed"] == 0
    assert result["failed"] == 0


def test_cycle_detected():
    p = Pipeline()
    a = TransformStage(lambda rows: rows, name="a")
    b = TransformStage(lambda rows: rows, name="b")
    p.add(a)
    p.add(b)
    p.connect(a, b)
    p.connect(b, a)
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "cycle" in str(excinfo.value)
    assert "a" in str(excinfo.value)
    assert "b" in str(excinfo.value)


def test_run_validates_pipeline():
    p = Pipeline()
    a = TransformStage(lambda rows: rows, name="a")
    b = TransformStage(lambda rows: rows, name="b")
    p.add(a)
    p.add(b)
    p.connect(a, b)
    p.connect(b, a)
    with pytest.raises(InvalidPipelineError):
        p.run([1, 2, 3])


def test_duplicate_names_detected():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="x"))
    p.add(TransformStage(lambda rows: rows, name="x"))
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "x" in str(excinfo.value)


def test_invalid_connection_unknown_dependency():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows, name="a"))
    p.add(TransformStage(lambda rows: rows, name="b"), depends_on="ghost")
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "ghost" in str(excinfo.value)


def test_invalid_connection_self_loop():
    p = Pipeline()
    a = TransformStage(lambda rows: rows, name="a")
    p.add(a)
    p.connect(a, a)
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "self-loop" in str(excinfo.value)


def test_isolation_continues_to_later_stages():
    counter = CountStage(name="counter")
    p = Pipeline()
    p.add(BoomStage())
    p.add(counter)
    result = p.run([1, 2, 3])
    assert result["failed"] == 3
    assert result["processed"] == 0
    assert counter.calls == 1
    stats = result["stage_stats"]["stage_1"]
    assert stats["failures"] == 1
    assert stats["last_error"] is not None


def test_isolation_per_batch_continues():
    counter = CountStage(name="counter")
    p = Pipeline()
    p.add(BoomStage())
    p.add(counter)
    result = p.run([1, 2, 3], batch_size=1)
    assert result["failed"] == 3
    assert counter.calls == 3


def test_processed_failed_invariant():
    p = Pipeline()
    p.add(BoomStage())
    result = p.run([1, 2, 3, 4, 5], batch_size=2)
    assert result["processed"] + result["failed"] == 5


def test_fail_fast_raises_stage_failure():
    p = Pipeline()
    p.add(BoomStage())
    with pytest.raises(StageFailure):
        p.run([1, 2, 3], fail_fast=True)


def test_batch_size_must_be_positive():
    p = Pipeline()
    p.add(TransformStage(lambda rows: rows))
    with pytest.raises(ValueError):
        p.run([1], batch_size=0)


def test_fan_in_rejected_at_validation():
    p = Pipeline()
    a = TransformStage(lambda rows: rows, name="a")
    b = TransformStage(lambda rows: rows, name="b")
    c = TransformStage(lambda rows: rows, name="c")
    p.add(a)
    p.add(b, depends_on="a")
    p.add(c)
    p.connect(a, c)
    p.connect(b, c)
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "immediate predecessor" in str(excinfo.value)


def test_dependency_contradicting_insertion_order_rejected():
    p = Pipeline()
    a = TransformStage(lambda rows: rows, name="a")
    b = TransformStage(lambda rows: rows, name="b")
    p.add(b, depends_on="a")
    p.add(a)
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "b" in str(excinfo.value)
    assert "immediate predecessor" in str(excinfo.value)


def test_skipped_predecessor_dependency_rejected():
    p = Pipeline()
    a = TransformStage(lambda rows: rows, name="a")
    b = TransformStage(lambda rows: rows, name="b")
    c = TransformStage(lambda rows: rows, name="c")
    p.add(a)
    p.add(b)
    p.add(c, depends_on="a")
    with pytest.raises(InvalidPipelineError) as excinfo:
        p.validate()
    assert "immediate predecessor" in str(excinfo.value)
