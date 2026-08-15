import threading
import time

import pytest

from _testutil import NOOP_SLEEP, wait_status
from api import Scheduler
from clock import Clock
from errors import (
    DuplicateJobError,
    ExecutorFullError,
    InvalidJobError,
    JobNotFoundError,
    JobTimeoutError,
)
from executor import Executor
from job_store import Job
from metrics import Metrics
from priority_queue import PriorityQueue


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def test_metrics_snapshot():
    m = Metrics()
    m.inc("submitted")
    m.inc("failed", 2)
    assert m.get("submitted") == 1
    assert m.snapshot() == {
        "submitted": 1,
        "succeeded": 0,
        "failed": 2,
        "retried": 0,
        "recovered": 0,
        "deadline_hit": 0,
    }
    with pytest.raises(ValueError):
        m.inc("nope")


# ---------------------------------------------------------------------------
# priority queue: priority + FIFO, priority change, aging
# ---------------------------------------------------------------------------


def test_priority_queue_priority_and_fifo():
    q = PriorityQueue(aging_threshold=None, clock=Clock(lambda: 0.0))
    q.put(5, "a", enqueued_at=0.0)
    q.put(1, "b", enqueued_at=1.0)
    q.put(5, "c", enqueued_at=2.0)
    assert q.pop() == (2, "b")
    assert q.pop() == (1, "a")
    assert q.pop() == (3, "c")
    assert q.pop() is None
    assert len(q) == 0


def test_priority_queue_change_priority():
    q = PriorityQueue(aging_threshold=None, clock=Clock(lambda: 0.0))
    q.put(9, "x", enqueued_at=0.0)
    q.put(0, "y", enqueued_at=1.0)
    assert q.change_priority("x", -1) is True
    assert q.pop() == (3, "x")
    assert q.pop() == (2, "y")
    assert q.change_priority("missing", 0) is False


def test_priority_queue_aging_promotes_starved_low_priority():
    t = [0.0]
    q = PriorityQueue(aging_threshold=5.0, clock=Clock(lambda: t[0]))
    q.put(10, "low", enqueued_at=0.0)
    for i in range(50):
        q.put(0, f"high{i}", enqueued_at=t[0])
        t[0] += 0.01
    assert q.peek() == (2, "high0")
    assert q.pop() == (2, "high0")
    t[0] = 6.0
    assert q.pop() == (1, "low")
    assert q.pop() == (3, "high1")
    assert q.pop() == (4, "high2")


def test_priority_queue_strict_when_aging_disabled():
    t = [0.0]
    q = PriorityQueue(aging_threshold=None, clock=Clock(lambda: t[0]))
    q.put(10, "low", enqueued_at=0.0)
    for i in range(50):
        q.put(0, f"high{i}", enqueued_at=t[0])
        t[0] += 0.01
    t[0] = 1000.0
    for i in range(50):
        seq, job_id = q.pop()
        assert job_id == f"high{i}"
    assert q.pop() == (1, "low")


def test_priority_queue_not_aged_below_threshold():
    q = PriorityQueue(aging_threshold=5.0, clock=Clock(lambda: 1.0))
    q.put(10, "low", enqueued_at=0.0)
    q.put(0, "high", enqueued_at=0.0)
    assert q.pop() == (2, "high")


# ---------------------------------------------------------------------------
# scheduler: submit / get / status / validation
# ---------------------------------------------------------------------------


def test_submit_get_status(tmp_path):
    s = Scheduler(str(tmp_path / "wal.log"), workers=2, sleep_fn=NOOP_SLEEP)
    try:
        r = s.submit("j1", lambda job: "done", payload={"x": 1})
        assert r.job_id == "j1"
        assert r.duplicate is False
        assert s.status("j1") == "queued"
        wait_status(s, "j1", "succeeded")
        job = s.get("j1")
        assert job.status == "succeeded"
        assert job.result == "done"
        with pytest.raises(JobNotFoundError):
            s.get("missing")
        with pytest.raises(JobNotFoundError):
            s.status("missing")
    finally:
        s.shutdown()


def test_submit_invalid_raises(tmp_path):
    s = Scheduler(str(tmp_path / "wal.log"), workers=1, sleep_fn=NOOP_SLEEP)
    try:
        with pytest.raises(InvalidJobError):
            s.submit("", lambda j: None)
        with pytest.raises(InvalidJobError):
            s.submit("j1", None)
        with pytest.raises(InvalidJobError):
            s.submit("j1", lambda j: None, priority="high")
        with pytest.raises(InvalidJobError):
            s.submit("j1", lambda j: None, idempotency_key="")
        with pytest.raises(InvalidJobError):
            s.submit("j1", lambda j: None, timeout=-1)
        with pytest.raises(InvalidJobError):
            s.submit("j1", lambda j: None, max_attempts=0)
        with pytest.raises(InvalidJobError):
            s.submit("j1", lambda j: None, payload=object())
    finally:
        s.shutdown()


def test_duplicate_job_id_raises(tmp_path):
    s = Scheduler(str(tmp_path / "wal.log"), workers=1, sleep_fn=NOOP_SLEEP)
    try:
        s.submit("j1", lambda j: None)
        with pytest.raises(DuplicateJobError):
            s.submit("j1", lambda j: None)
    finally:
        s.shutdown()


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------


def test_idempotency_duplicate_submit(tmp_path):
    s = Scheduler(str(tmp_path / "wal.log"), workers=2, sleep_fn=NOOP_SLEEP)
    try:
        r1 = s.submit("id1", lambda j: 1, idempotency_key="K")
        r2 = s.submit("id2", lambda j: 2, idempotency_key="K")
        assert r1.duplicate is False
        assert r2.duplicate is True
        assert r2.existing_job_id == "id1"
        assert r2.job_id == "id1"
        assert s.status("id1") in ("queued", "running", "succeeded")
        with pytest.raises(JobNotFoundError):
            s.get("id2")
        assert s.stats()["total"] == 1
    finally:
        s.shutdown()


# ---------------------------------------------------------------------------
# retry / timeout
# ---------------------------------------------------------------------------


def test_retry_succeeds_on_second_attempt(tmp_path):
    calls = [0]

    def flaky(job):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("boom")
        return "ok"

    s = Scheduler(
        str(tmp_path / "wal.log"), workers=2, sleep_fn=NOOP_SLEEP, base_backoff=0.0, max_attempts=3
    )
    try:
        s.submit("r1", flaky)
        wait_status(s, "r1", "succeeded")
        job = s.get("r1")
        assert job.attempts == 2
        assert job.result == "ok"
        assert s.stats()["retried"] == 1
        assert calls[0] == 2
    finally:
        s.shutdown()


def test_retry_exhausted_marks_failed(tmp_path):
    calls = [0]

    def always_fail(job):
        calls[0] += 1
        raise ValueError("nope")

    s = Scheduler(
        str(tmp_path / "wal.log"), workers=2, sleep_fn=NOOP_SLEEP, base_backoff=0.0, max_attempts=3
    )
    try:
        s.submit("f1", always_fail)
        wait_status(s, "f1", "failed")
        job = s.get("f1")
        assert job.attempts == 3
        assert job.error_type == "ValueError"
        assert s.stats()["retried"] == 2
        assert s.stats()["failed"] == 1
        assert calls[0] == 3
    finally:
        s.shutdown()


def test_timeout_raises_and_worker_reclaimed(tmp_path):
    s = Scheduler(
        str(tmp_path / "wal.log"), workers=2, sleep_fn=NOOP_SLEEP, base_backoff=0.0, max_attempts=3
    )
    try:

        def slow(job):
            time.sleep(0.5)
            return "late"

        s.submit("t1", slow, timeout=0.05)
        wait_status(s, "t1", "failed")
        job = s.get("t1")
        assert job.error_type == "JobTimeoutError"
        assert job.timeout_hits == 3
        assert s.stats()["deadline_hit"] == 3
        assert s.stats()["failed"] == 1

        s.submit("t2", lambda j: "ok", timeout=1.0)
        wait_status(s, "t2", "succeeded")
        assert s.get("t2").result == "ok"
    finally:
        s.shutdown()


def test_executor_run_sync_timeout_raises():
    ex = Executor(workers=1, sleep_fn=NOOP_SLEEP, base_backoff=0.0)
    try:

        def slow(job):
            time.sleep(5)

        job = Job(job_id="t", func=slow, timeout=0.05, max_attempts=1)
        with pytest.raises(JobTimeoutError):
            ex.run_sync(job)
        assert job.status == "failed"
        assert job.error_type == "JobTimeoutError"
    finally:
        ex.shutdown(wait=False)


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


def test_cancel_queued_job(tmp_path):
    s = Scheduler(
        str(tmp_path / "wal.log"),
        workers=1,
        sleep_fn=NOOP_SLEEP,
        base_backoff=0.0,
        max_attempts=1,
    )
    try:
        s.submit("run", lambda j: "ok")
        wait_status(s, "run", "succeeded")
        s.submit("cancel-me", lambda j: "never")
        assert s.cancel("cancel-me") is True
        wait_status(s, "cancel-me", "cancelled")
        assert s.cancel("cancel-me") is False
        assert s.cancel("missing") is False
    finally:
        s.shutdown()


# ---------------------------------------------------------------------------
# snapshot / replay / stats
# ---------------------------------------------------------------------------


def test_snapshot_and_replay(tmp_path):
    wal = str(tmp_path / "wal.log")
    s = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP)
    try:
        s.submit("a", lambda j: 1)
        s.submit("b", lambda j: 2, idempotency_key="K")
        wait_status(s, "a", "succeeded")
        wait_status(s, "b", "succeeded")
        assert s.replay() == 4
        s.snapshot()
        assert s.replay() == 0
        assert s.stats()["succeeded"] == 2
        s.submit("c", lambda j: 3)
        wait_status(s, "c", "succeeded")
        assert s.replay() == 2
    finally:
        s.shutdown()

    s2 = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP)
    try:
        recovered = s2.recover()
        assert recovered == []
        assert s2.get("a").status == "succeeded"
        assert s2.get("b").status == "succeeded"
        r = s2.submit("d", lambda j: 4, idempotency_key="K")
        assert r.duplicate is True
        assert r.existing_job_id == "b"
    finally:
        s2.shutdown()


def test_stats_counts(tmp_path):
    s = Scheduler(str(tmp_path / "wal.log"), workers=2, sleep_fn=NOOP_SLEEP)
    try:
        s.submit("a", lambda j: 1)
        s.submit("b", lambda j: 2)
        wait_status(s, "a", "succeeded")
        wait_status(s, "b", "succeeded")
        stats = s.stats()
        assert stats["submitted"] == 2
        assert stats["succeeded"] == 2
        assert stats["total"] == 2
        assert stats["queued"] == 0
        assert stats["running"] == 0
    finally:
        s.shutdown()


# ---------------------------------------------------------------------------
# executor capacity
# ---------------------------------------------------------------------------


def test_executor_full_raises_immediately():
    block = threading.Event()
    ex = Executor(workers=1, queue_size=1)
    try:
        job_a = Job(job_id="a", func=lambda j: block.wait())
        job_b = Job(job_id="b", func=lambda j: block.wait())
        job_c = Job(job_id="c", func=lambda j: block.wait())
        ex.submit(job_a)
        time.sleep(0.05)
        ex.submit(job_b)
        with pytest.raises(ExecutorFullError):
            ex.submit(job_c)
    finally:
        block.set()
        ex.shutdown(wait=False)
