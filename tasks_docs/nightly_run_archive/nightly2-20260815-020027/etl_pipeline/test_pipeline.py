import pytest

from errors import InvalidPipelineError, StageFailure
from pipeline import Pipeline
from stages import BatchSink, FilterStage, RetryStage, TransformStage


def test_add_is_idempotent_and_auto_names():
    pipeline = Pipeline()
    first = TransformStage(lambda rows: rows)
    second = FilterStage(lambda row: True)
    pipeline.add(first).add(second)
    assert pipeline.stage_names == ["stage_0", "stage_1"]
    pipeline.add(first)
    assert pipeline.stage_names == ["stage_0", "stage_1"]


def test_add_preserves_explicit_name():
    pipeline = Pipeline()
    pipeline.add(TransformStage(lambda rows: rows, name="custom"))
    assert pipeline.stage_names == ["custom"]


def test_add_rejects_duplicate_explicit_name():
    pipeline = Pipeline()
    pipeline.add(TransformStage(lambda rows: rows, name="dup"))
    with pytest.raises(InvalidPipelineError):
        pipeline.add(TransformStage(lambda rows: rows, name="dup"))


def test_validate_rejects_cycle_with_listed_path():
    pipeline = Pipeline()
    first = TransformStage(lambda rows: rows, name="A")
    second = TransformStage(lambda rows: rows, name="B")
    pipeline.add(first).add(second)
    pipeline.connect("A", "B")
    pipeline.connect("B", "A")
    with pytest.raises(InvalidPipelineError) as excinfo:
        pipeline.validate()
    assert excinfo.value.cycle == ["A", "B", "A"]
    assert "A -> B -> A" in str(excinfo.value)


def test_validate_rejects_unknown_connection():
    pipeline = Pipeline()
    pipeline.add(TransformStage(lambda rows: rows, name="A"))
    with pytest.raises(InvalidPipelineError):
        pipeline.connect("A", "ghost")


def test_validate_rejects_self_loop():
    pipeline = Pipeline()
    stage = TransformStage(lambda rows: rows, name="A")
    pipeline.add(stage)
    with pytest.raises(InvalidPipelineError):
        pipeline.connect(stage, stage)


def test_validate_ok_on_linear_pipeline():
    pipeline = Pipeline()
    pipeline.add(TransformStage(lambda rows: rows))
    pipeline.add(BatchSink(limit=10))
    assert pipeline.validate() is pipeline


def test_run_basic_returns_stats():
    sink = BatchSink(limit=100)
    pipeline = Pipeline()
    pipeline.add(TransformStage(lambda rows: [row * 2 for row in rows]))
    pipeline.add(FilterStage(lambda value: value % 4 == 0))
    pipeline.add(sink)
    result = pipeline.run([1, 2, 3, 4, 5, 6])
    assert result["processed"] == 6
    assert result["failed"] == 0
    assert result["failures"] == []
    assert set(result["stage_stats"]) == {"stage_0", "stage_1", "stage_2"}


def test_run_isolates_failed_batch_and_continues():
    def boom(rows):
        if any("bad" in row for row in rows):
            raise ValueError("bad row")
        return [row.upper() for row in rows]

    sink = BatchSink(limit=100)
    pipeline = Pipeline()
    pipeline.add(TransformStage(boom, name="transform"))
    pipeline.add(sink)
    result = pipeline.run(["good", "bad", "nice"], batch_size=1)

    assert result["processed"] == 2
    assert result["failed"] == 1
    assert result["stage_stats"]["transform"]["failed"] == 1
    assert result["failures"][0]["stage"] == "transform"
    assert isinstance(result["failures"][0]["error"], ValueError)

    sink.flush()
    delivered = [row for batch in sink.rows for row in batch]
    assert delivered == ["GOOD", "NICE"]


def test_run_fail_fast_raises_stage_failure():
    def boom(rows):
        if any("bad" in row for row in rows):
            raise ValueError("bad row")
        return rows

    pipeline = Pipeline()
    pipeline.add(TransformStage(boom, name="transform"))
    pipeline.add(BatchSink(limit=100))
    with pytest.raises(StageFailure) as excinfo:
        pipeline.run(["good", "bad"], batch_size=1, fail_fast=True)
    assert excinfo.value.stage.name == "transform"
    assert isinstance(excinfo.value.cause, ValueError)


def test_run_with_retry_stage_succeeds():
    calls = {"n": 0}

    def flaky(rows):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return [row * 2 for row in rows]

    sink = BatchSink(limit=100)
    pipeline = Pipeline()
    pipeline.add(RetryStage(TransformStage(flaky), retries=2, backoff_base=0.0))
    pipeline.add(sink)
    result = pipeline.run([1, 2, 3])
    assert result["processed"] == 3
    assert result["failed"] == 0
    assert calls["n"] == 3


def test_run_empty_input_returns_zero_stats_without_calling_stages():
    calls = {"n": 0}

    def boom(rows):
        calls["n"] += 1
        raise ValueError("should not run")

    sink = BatchSink(limit=100)
    pipeline = Pipeline()
    pipeline.add(TransformStage(boom))
    pipeline.add(sink)
    result = pipeline.run([])
    assert calls["n"] == 0
    assert result == {
        "processed": 0,
        "failed": 0,
        "stage_stats": {
            "stage_0": {"in": 0, "out": 0, "failed": 0},
            "stage_1": {"in": 0, "out": 0, "failed": 0},
        },
        "failures": [],
    }


def test_run_validates_pipeline_before_executing():
    pipeline = Pipeline()
    first = TransformStage(lambda rows: rows, name="A")
    second = TransformStage(lambda rows: rows, name="B")
    pipeline.add(first).add(second)
    pipeline.connect("B", "A")
    with pytest.raises(InvalidPipelineError):
        pipeline.run([1])
