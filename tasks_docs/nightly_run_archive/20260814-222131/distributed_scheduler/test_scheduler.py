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
from job_store import JobRecord, JobStore
from metrics import Metrics
from priority_queue import PriorityQueue


def no_sleep(_):
    pass


def wait_until(predicate, timeout=5.0, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def monotonic(self):
        return self.t

    def advance(self, delta):
        self.t += delta


def make_job(job_id, priority):
    return JobRecord(job_id=job_id, task="t", priority=priority)


# -- priority queue -----------------------------------------------------------


def test_priority_order_and_fifo():
    pq = PriorityQueue(aging_interval=None)
    pq.push(make_job("a", 1))
    pq.push(make_job("b", 0))
    pq.push(make_job("c", 0))
    pq.push(make_job("d", 2))
    assert pq.pop().job_id == "b"
    assert pq.pop().job_id == "c"
    assert pq.pop().job_id == "a"
    assert pq.pop().job_id == "d"
    assert pq.pop() is None


def test_aging_eventually_dispatches_low_priority():
    clock = FakeClock()
    pq = PriorityQueue(aging_interval=5.0, clock=clock.monotonic)
    low = make_job("low", 100)
    pq.push(low)
    for i in range(200):
        pq.push(make_job(f"h{i}", 0))
        clock.advance(5.0)
        popped = pq.pop()
        if popped is not None and popped.job_id == "low":
            return
    assert False, "low-priority job was starved forever"


def test_aging_keeps_low_priority_waiting_until_its_age_budget():
    clock = FakeClock()
    pq = PriorityQueue(aging_interval=5.0, clock=clock.monotonic)
    low = make_job("low", 10)
    pq.push(low)
    for i in range(10):
        pq.push(make_job(f"h{i}", 0))
        popped = pq.pop()
        assert popped.job_id == f"h{i}"
        clock.advance(0.5)
    clock.advance(60.0)
    assert pq.pop().job_id == "low"


def test_priority_change_reflected():
    pq = PriorityQueue(aging_interval=None)
    a = make_job("a", 5)
    b = make_job("b", 1)
    pq.push(a)
    pq.push(b)
    a.priority = 0
    pq.update_priority(a)
    assert pq.pop().job_id == "a"
    assert pq.pop().job_id == "b"


def test_remove_cancels_queued_job():
    pq = PriorityQueue(aging_interval=None)
    pq.push(make_job("a", 0))
    pq.push(make_job("b", 0))
    pq.remove("a")
    assert pq.pop().job_id == "b"
    assert pq.pop() is None


# -- scheduler integration ----------------------------------------------------


def test_submit_get_status(tmp_path):
    with Scheduler(tmp_path, pool_size=1, tasks={"t": lambda: 42}) as s:
        jid = s.submit("t")
        record = s.get(jid)
        assert record.job_id == jid
        assert record.task == "t"
        assert s.status(jid) in ("queued", "running", "completed")
        assert wait_until(lambda: s.status(jid) == "completed")
        assert s.get(jid).result == 42


def test_job_not_found(tmp_path):
    with Scheduler(tmp_path, tasks={"t": lambda: 1}) as s:
        with pytest.raises(JobNotFoundError):
            s.get("nope")
        with pytest.raises(JobNotFoundError):
            s.status("nope")
        with pytest.raises(JobNotFoundError):
            s.cancel("nope")


def test_invalid_arguments(tmp_path):
    with Scheduler(tmp_path, tasks={"t": lambda: 1}) as s:
        with pytest.raises(InvalidJobError):
            s.submit("missing")
        with pytest.raises(InvalidJobError):
            s.submit("t", priority="high")
        with pytest.raises(InvalidJobError):
            s.submit("t", timeout=-1)
        with pytest.raises(InvalidJobError):
            s.submit("t", timeout=0)
        with pytest.raises(InvalidJobError):
            s.submit("t", max_retries=-1)
        with pytest.raises(InvalidJobError):
            s.submit("t", idempotency_key="")
        with pytest.raises(InvalidJobError):
            s.submit("t", bad_arg=object())
        jid = s.submit("t")
        with pytest.raises(InvalidJobError):
            s.set_priority(jid, "high")


def test_retry_succeeds_on_second_attempt(tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first attempt fails")
        return "ok"

    with Scheduler(tmp_path, pool_size=1, tasks={"flaky": flaky},
                   sleep_fn=no_sleep, base_backoff=0) as s:
        jid = s.submit("flaky", max_retries=3)
        assert wait_until(lambda: s.status(jid) == "completed")
        assert calls["n"] == 2
        assert s.get(jid).result == "ok"
        stats = s.stats()["metrics"]
        assert stats["retried"] == 1
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0


def test_retries_exhausted_marks_failed(tmp_path):
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise ValueError("boom")

    with Scheduler(tmp_path, pool_size=1, tasks={"f": always_fail},
                   sleep_fn=no_sleep, base_backoff=0) as s:
        jid = s.submit("f", max_retries=2)
        assert wait_until(lambda: s.status(jid) == "failed")
        assert calls["n"] == 3
        stats = s.stats()["metrics"]
        assert stats["failed"] == 1
        assert stats["retried"] == 2
        assert "boom" in str(s.get(jid).error)


def test_timeout_raises_job_timeout_and_reclaims_slot(tmp_path):
    def slow():
        time.sleep(0.3)
        return "too late"

    with Scheduler(tmp_path, pool_size=1, tasks={"slow": slow, "fast": lambda: 7},
                   sleep_fn=no_sleep) as s:
        jid = s.submit("slow", timeout=0.05, max_retries=0)
        assert wait_until(lambda: s.status(jid) == "failed")
        record = s.get(jid)
        assert record.state == "failed"
        assert isinstance(record.error, JobTimeoutError)
        stats = s.stats()["metrics"]
        assert stats["deadline_hit"] == 1
        assert stats["failed"] == 1
        fast = s.submit("fast")
        assert wait_until(lambda: s.status(fast) == "completed")
        assert s.get(fast).result == 7


def test_cancel_queued_not_executed(tmp_path):
    executed = {"n": 0}
    gate = threading.Event()

    def blocked():
        executed["n"] += 1
        gate.wait(5)
        return 1

    with Scheduler(tmp_path, pool_size=1, tasks={"b": blocked}) as s:
        blocker = s.submit("b")
        assert wait_until(lambda: s.status(blocker) == "running")
        jid = s.submit("b")
        assert s.status(jid) == "queued"
        assert s.cancel(jid) is True
        assert s.status(jid) == "cancelled"
        gate.set()
        assert wait_until(lambda: s.status(blocker) == "completed")
        assert executed["n"] == 1


def test_cancel_running_discards_result(tmp_path):
    gate = threading.Event()

    def blocked():
        gate.wait(5)
        return "done"

    with Scheduler(tmp_path, pool_size=1, tasks={"b": blocked}) as s:
        jid = s.submit("b")
        assert wait_until(lambda: s.status(jid) == "running")
        assert s.cancel(jid) is True
        gate.set()
        time.sleep(0.1)
        assert s.status(jid) == "cancelled"
        assert s.stats()["metrics"]["succeeded"] == 0


def test_idempotency_duplicate_submit_any_state(tmp_path):
    calls = {"n": 0}

    def t():
        calls["n"] += 1
        return calls["n"]

    with Scheduler(tmp_path, pool_size=1, tasks={"t": t}) as s:
        jid = s.submit("t", idempotency_key="K")
        with pytest.raises(DuplicateJobError) as exc:
            s.submit("t", idempotency_key="K")
        assert exc.value.existing_job_id == jid
        assert wait_until(lambda: s.status(jid) == "completed")
        with pytest.raises(DuplicateJobError):
            s.submit("t", idempotency_key="K")
        assert calls["n"] == 1


def test_distinct_idempotency_keys_are_distinct_jobs(tmp_path):
    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s:
        a = s.submit("t", idempotency_key="A")
        b = s.submit("t", idempotency_key="B")
        assert a != b
        assert wait_until(lambda: s.status(a) == "completed")
        assert wait_until(lambda: s.status(b) == "completed")


def test_stats_snapshot_replay(tmp_path):
    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s:
        jids = [s.submit("t") for _ in range(3)]
        assert wait_until(lambda: all(s.status(j) == "completed" for j in jids))
        stats = s.stats()
        assert stats["metrics"]["submitted"] == 3
        assert stats["metrics"]["succeeded"] == 3
        assert stats["jobs"]["completed"] == 3
        assert stats["queued"] == 0
        before = s.replay()
        assert before == 9
        s.snapshot()
        after = s.replay()
        assert after == 0
        assert all(s.status(j) == "completed" for j in jids)
    with Scheduler(tmp_path, tasks={"t": lambda: 1}) as s2:
        s2.recover()
        assert s2.status(jids[0]) == "completed"
        assert s2.replay() == 0


def test_low_priority_eventually_runs_under_flood(tmp_path):
    executed = {"low": 0}

    def task_low():
        executed["low"] += 1
        return 1

    with Scheduler(tmp_path, pool_size=1, tasks={"t": task_low, "h": lambda: 1},
                   aging_interval=0.001, sleep_fn=no_sleep) as s:
        low = s.submit("t", priority=1000)
        for _ in range(500):
            s.submit("h", priority=0)
        assert wait_until(lambda: s.status(low) == "completed", timeout=15.0)
        assert executed["low"] == 1


# -- executor direct ----------------------------------------------------------


def test_executor_full_error(tmp_path):
    gate = threading.Event()
    store = JobStore(str(tmp_path / "ex"))
    metrics = Metrics()
    executor = Executor(pool_size=1, store=store, metrics=metrics, sleep_fn=no_sleep)
    try:
        blocker = JobRecord(job_id="blocker", task="t")
        store.add(blocker)
        executor.submit(store.get("blocker"), lambda job: gate.wait(5))
        assert executor.free_slots() == 0
        second = JobRecord(job_id="second", task="t")
        store.add(second)
        with pytest.raises(ExecutorFullError):
            executor.submit(store.get("second"), lambda job: 1)
    finally:
        gate.set()
        executor.shutdown()
