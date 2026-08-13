"""Unit + integration tests for the Scheduler facade and core modules."""

import threading
import time

import pytest

from api import Scheduler
from errors import (
    DuplicateJobError,
    ExecutorFullError,
    InvalidJobError,
    JobNotFoundError,
    JobTimeoutError,
)
from executor import Executor
from job_store import Job, QUEUED, SUCCEEDED, FAILED
from priority_queue import PriorityQueue
from test_helpers import FakeClock, wait_until


# --------------------------------------------------------------------------
# Priority queue: strict priority, FIFO tie-break, priority changes, age boost
# --------------------------------------------------------------------------

def test_pq_strict_priority_order():
    pq = PriorityQueue()
    pq.put("low", priority=10)
    pq.put("high", priority=0)
    pq.put("mid", priority=5)
    assert pq.pop() == "high"
    assert pq.pop() == "mid"
    assert pq.pop() == "low"


def test_pq_fifo_tie_break():
    pq = PriorityQueue()
    pq.put("a", priority=0)
    pq.put("b", priority=0)
    pq.put("c", priority=0)
    assert pq.pop() == "a"
    assert pq.pop() == "b"
    assert pq.pop() == "c"


def test_pq_priority_change_reorders():
    pq = PriorityQueue()
    pq.put("a", priority=0)
    pq.put("b", priority=0)
    pq.put("c", priority=0)
    assert pq.update_priority("c", -5) is True
    assert pq.pop() == "c"
    assert pq.pop() == "a"
    assert pq.pop() == "b"


def test_pq_age_boost_beats_new_high_priority():
    clock = FakeClock(t=100.0)
    pq = PriorityQueue(clock=clock, boost_interval=1.0, boost_step=1)
    pq.put("low", priority=10)          # eff 10, seq 0
    clock.advance(11)                    # low's boost = 11 -> eff = -1
    pq.put("high", priority=0)           # eff 0, seq 1
    assert pq.pop() == "low"             # boosted low outranks fresh high


def test_pq_age_boost_tie_breaks_by_fifo():
    clock = FakeClock(t=100.0)
    pq = PriorityQueue(clock=clock, boost_interval=1.0, boost_step=1)
    pq.put("old_low", priority=10)
    clock.advance(10)                    # old_low boost=10 -> eff 0 == high
    pq.put("fresh_high", priority=0)     # eff 0
    assert pq.pop() == "old_low"         # FIFO by enqueue seq at equal eff


def test_pq_age_boost_never_regresses_with_frozen_clock():
    clock = FakeClock(t=0.0)
    pq = PriorityQueue(clock=clock, boost_interval=1.0, boost_step=1)
    pq.put("only", priority=5)
    assert pq.pop() == "only"


def test_pq_age_boost_guarantees_eventual_scheduling_under_sustained_high_prio():
    clock = FakeClock(t=0.0)
    pq = PriorityQueue(clock=clock, boost_interval=1.0, boost_step=1)
    pq.put("low", priority=100)
    clock.advance(101)  # low waits 101 intervals -> boost 101 -> eff = -1
    for i in range(50):
        pq.put("high-{}".format(i), priority=0)
    assert pq.pop() == "low"


def test_pq_age_boost_waits_only_after_interval():
    clock = FakeClock(t=0.0)
    pq = PriorityQueue(clock=clock, boost_interval=1.0, boost_step=1)
    pq.put("low", priority=10)
    clock.advance(0.5)  # less than one interval: no boost yet
    pq.put("high", priority=0)
    assert pq.pop() == "high"


def test_pq_remove():
    pq = PriorityQueue()
    pq.put("a", priority=0)
    pq.put("b", priority=0)
    pq.remove("a")
    assert pq.pop() == "b"


# --------------------------------------------------------------------------
# Submission / lookup / status / stats / validation
# --------------------------------------------------------------------------

def test_submit_get_status(tmp_path):
    s = Scheduler(wal_path=tmp_path / "w.log", auto_start=False)
    job_id = s.submit(lambda: 42, priority=3, timeout=1.0, max_retries=1)
    assert s.status(job_id) == QUEUED
    assert s.get(job_id).priority == 3
    assert s.get(job_id).timeout == 1.0
    assert s.get(job_id).max_retries == 1
    with pytest.raises(JobNotFoundError):
        s.get("nope")


def test_submit_validation(tmp_path):
    s = Scheduler(wal_path=tmp_path / "w.log", auto_start=False)
    with pytest.raises(InvalidJobError):
        s.submit(None)
    with pytest.raises(InvalidJobError):
        s.submit(lambda: 1, priority=1.5)
    with pytest.raises(InvalidJobError):
        s.submit(lambda: 1, priority=True)
    with pytest.raises(InvalidJobError):
        s.submit(lambda: 1, timeout=-1)
    with pytest.raises(InvalidJobError):
        s.submit(lambda: 1, max_retries=-2)
    with pytest.raises(InvalidJobError):
        s.submit(lambda: 1, idempotency_key="")
    with pytest.raises(InvalidJobError):
        s.priority("missing", "not-an-int")


def test_stats_counts(tmp_path):
    s = Scheduler(wal_path=tmp_path / "w.log", num_workers=2, auto_start=True)
    try:
        for _ in range(3):
            s.submit(lambda: None, max_retries=0)
        assert wait_until(lambda: s.stats()["metrics"]["succeeded"] == 3)
        stats = s.stats()
        assert stats["total"] == 3
        assert stats["metrics"]["submitted"] == 3
        assert stats["metrics"]["succeeded"] == 3
    finally:
        s.close()


def test_cancel_queued_job_not_executed(tmp_path):
    executed = []
    release = threading.Event()
    s = Scheduler(wal_path=tmp_path / "w.log", num_workers=1, auto_start=True)
    try:
        jid = s.submit(lambda: (release.wait(60), executed.append(1)))
        assert s.cancel(jid) is True
        assert wait_until(lambda: s.status(jid) == "canceled")
        time.sleep(0.1)
        assert executed == []
        assert s.cancel(jid) is False
    finally:
        release.set()
        s.close()


# --------------------------------------------------------------------------
# Retry: second-attempt success / permanent failure / backoff applied
# --------------------------------------------------------------------------

def test_retry_succeeds_on_second_attempt(tmp_path):
    calls = []
    sleeps = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("flaky")
        return "ok"

    s = Scheduler(
        wal_path=tmp_path / "w.log", num_workers=1,
        rng=lambda: 1.0, sleep=lambda d: sleeps.append(d),
    )
    try:
        jid = s.submit(fn, max_retries=1, timeout=5.0)
        assert wait_until(lambda: s.status(jid) == SUCCEEDED)
        assert s.get(jid).result == "ok"
        assert s.stats()["metrics"]["retried"] == 1
        assert s.stats()["metrics"]["succeeded"] == 1
        assert len(sleeps) >= 1
    finally:
        s.close()


def test_retry_exhausted_marks_failed(tmp_path):
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("always broken")

    s = Scheduler(
        wal_path=tmp_path / "w.log", num_workers=1,
        rng=lambda: 1.0, base_backoff=0.01, max_backoff=0.02,
    )
    try:
        jid = s.submit(fn, max_retries=2, timeout=5.0)
        assert wait_until(lambda: s.status(jid) == FAILED)
        assert len(calls) == 3
        stats = s.stats()["metrics"]
        assert stats["retried"] == 2
        assert stats["failed"] == 1
        assert "always broken" in s.get(jid).error
    finally:
        s.close()


# --------------------------------------------------------------------------
# Timeout: JobTimeoutError raised, job reclaimed, deadline_hit counted
# --------------------------------------------------------------------------

def test_executor_run_job_raises_jobtimeout():
    job = Job(job_id="x", fn=lambda: time.sleep(10), priority=0,
              timeout=0.05, max_retries=0, created_at=0.0)
    executor = Executor(num_workers=1)
    with pytest.raises(JobTimeoutError):
        executor.run_job(job)


def test_executor_dispatch_raises_when_full():
    job1 = Job(job_id="a", fn=lambda: None, priority=0, timeout=1.0,
               max_retries=0, created_at=0.0)
    job2 = Job(job_id="b", fn=lambda: None, priority=0, timeout=1.0,
               max_retries=0, created_at=0.0)
    executor = Executor(num_workers=1, max_pending=1)
    executor.dispatch(job1)
    with pytest.raises(ExecutorFullError):
        executor.dispatch(job2)


def test_timeout_job_fails_and_slot_reclaimed(tmp_path):
    s = Scheduler(wal_path=tmp_path / "w.log", num_workers=1)
    try:
        slow = s.submit(lambda: time.sleep(1.0), timeout=0.05, max_retries=0)
        assert wait_until(lambda: s.status(slow) == FAILED)
        assert s.stats()["metrics"]["deadline_hit"] == 1
        assert "timeout" in s.get(slow).error.lower()
        fast = s.submit(lambda: "reclaimed", timeout=5.0)
        assert wait_until(lambda: s.status(fast) == SUCCEEDED)
        assert s.get(fast).result == "reclaimed"
    finally:
        s.close()


# --------------------------------------------------------------------------
# Idempotency: duplicate key rejected, no new job created
# --------------------------------------------------------------------------

def test_idempotency_duplicate_submit(tmp_path):
    runs = []
    s = Scheduler(wal_path=tmp_path / "w.log", num_workers=1)
    try:
        jid = s.submit(lambda: runs.append(1), idempotency_key="k1")
        with pytest.raises(DuplicateJobError) as exc_info:
            s.submit(lambda: None, idempotency_key="k1")
        assert exc_info.value.job_id == jid
        assert s.stats()["total"] == 1
        assert wait_until(lambda: s.status(jid) == SUCCEEDED)
        assert runs == [1]
    finally:
        s.close()


# --------------------------------------------------------------------------
# WAL replay count and snapshot checkpoint
# --------------------------------------------------------------------------

def test_replay_count_grows_with_events(tmp_path):
    wal = tmp_path / "w.log"
    s = Scheduler(wal_path=wal, num_workers=1, auto_start=False)
    try:
        s.submit(lambda: None)
        assert s.replay() == 1
        s.submit(lambda: None)
        assert s.replay() == 2
    finally:
        s.close()


def test_snapshot_checkpoints_and_truncates(tmp_path):
    wal = tmp_path / "w.log"
    s = Scheduler(wal_path=wal, auto_start=False)
    for _ in range(3):
        s.submit(lambda: None)
    s.snapshot()
    assert s.replay() == 0
    s.submit(lambda: None)
    assert s.replay() == 1

    s2 = Scheduler(wal_path=wal, auto_start=False)
    recovered = s2.recover(fn_provider={})
    assert s2.stats()["total"] == 4
    assert recovered == 0
    assert s2.stats()["metrics"]["submitted"] == 4


def test_snapshot_does_not_double_apply(tmp_path):
    wal = tmp_path / "w.log"
    s = Scheduler(wal_path=wal, auto_start=False)
    for _ in range(2):
        s.submit(lambda: None)
    s.snapshot()
    s.close()

    s2 = Scheduler(wal_path=wal, auto_start=False)
    s2.recover(fn_provider={})
    assert s2.stats()["total"] == 2
    assert s2.stats()["metrics"]["submitted"] == 2
