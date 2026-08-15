import os
import threading
import time

import pytest

from errors import (
    DuplicateJobError,
    ExecutorFullError,
    InvalidJobError,
    JobNotFoundError,
    JobTimeoutError,
)
from priority_queue import PriorityQueue


def wait_terminal(scheduler, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = scheduler.status(job_id)
        if st.state in ("COMPLETED", "FAILED", "CANCELLED"):
            return st
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} not terminal: {scheduler.status(job_id)}")


def test_submit_and_get(make_scheduler):
    s = make_scheduler()

    def answer():
        return 42

    jid = s.submit(answer, max_retries=0)
    assert s.get(jid, timeout=5) == 42
    st = s.status(jid)
    assert st.state == "COMPLETED"
    stats = s.stats()
    assert stats["submitted"] == 1
    assert stats["succeeded"] == 1


def test_priority_order(make_scheduler):
    s = make_scheduler(worker_count=1, max_queued=100)
    order = []
    gate = threading.Event()

    def gatekeeper():
        gate.wait(5)

    def record(name):
        order.append(name)

    s.register_task("gatekeeper", gatekeeper)
    s.register_task("record", record)
    gid = s.submit("gatekeeper", priority=0, max_retries=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.status(gid).state == "RUNNING":
            break
        time.sleep(0.005)
    for prio in (2, 0, 1):
        s.submit("record", f"job-{prio}", priority=prio, max_retries=0)
    gate.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.stats()["succeeded"] >= 3:
            break
        time.sleep(0.005)
    assert order == ["job-0", "job-1", "job-2"]


def test_fifo_same_priority(make_scheduler):
    s = make_scheduler(worker_count=1, max_queued=100)
    order = []

    def record(name):
        order.append(name)

    s.register_task("record", record)
    for i in range(3):
        s.submit("record", f"f{i}", priority=0, max_retries=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.stats()["succeeded"] == 3:
            break
        time.sleep(0.005)
    assert order == ["f0", "f1", "f2"]


def test_change_priority(make_scheduler):
    s = make_scheduler(worker_count=1, max_queued=100)
    order = []
    evt = threading.Event()

    def block_record(name):
        order.append(name)
        evt.wait(5)

    s.register_task("block_record", block_record)
    j1 = s.submit("block_record", "a", priority=0, max_retries=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.status(j1).state == "RUNNING":
            break
        time.sleep(0.005)
    j2 = s.submit("block_record", "b", priority=5, max_retries=0)
    j3 = s.submit("block_record", "c", priority=3, max_retries=0)
    assert s.change_priority(j2, 1) is True
    evt.set()
    for j in (j1, j2, j3):
        s.get(j, timeout=5)
    assert order == ["a", "b", "c"]


def test_timeout_reclaims(make_scheduler):
    s = make_scheduler(worker_count=1)

    def slow():
        time.sleep(5)

    s.register_task("slow", slow)

    def quick():
        return "ok"

    s.register_task("quick", quick)
    jid = s.submit("slow", timeout=0.2, max_retries=0)
    with pytest.raises(JobTimeoutError):
        s.get(jid, timeout=2.0)
    stats = s.stats()
    assert stats["deadline_hit"] == 1
    assert stats["failed"] == 1
    assert s.status(jid).state == "FAILED"
    jid2 = s.submit("quick", max_retries=0)
    assert s.get(jid2, timeout=2.0) == "ok"


def test_retry_then_success(make_scheduler):
    s = make_scheduler(worker_count=1)
    state = {"calls": 0}

    def flaky():
        state["calls"] += 1
        if state["calls"] == 1:
            raise ValueError("boom")
        return "ok"

    s.register_task("flaky", flaky)
    jid = s.submit("flaky", max_retries=2)
    assert s.get(jid, timeout=5) == "ok"
    stats = s.stats()
    assert stats["retried"] == 1
    assert stats["succeeded"] == 1
    assert stats["failed"] == 0


def test_retry_exhausted(make_scheduler):
    s = make_scheduler(worker_count=1)
    state = {"calls": 0}

    def always_fail():
        state["calls"] += 1
        raise RuntimeError("nope")

    s.register_task("always_fail", always_fail)
    jid = s.submit("always_fail", max_retries=2)
    with pytest.raises(RuntimeError):
        s.get(jid, timeout=5)
    stats = s.stats()
    assert stats["retried"] == 2
    assert stats["failed"] == 1
    assert state["calls"] == 3
    assert s.status(jid).state == "FAILED"


def test_idempotent_completed(make_scheduler):
    s = make_scheduler()
    counter = []

    def f():
        counter.append(1)
        return "x"

    s.register_task("f", f)
    j1 = s.submit("f", idempotency_key="K", max_retries=0)
    assert s.get(j1, timeout=5) == "x"
    with pytest.raises(DuplicateJobError):
        s.submit("f", idempotency_key="K", max_retries=0)
    assert s.stats()["submitted"] == 1
    assert len(counter) == 1


def test_idempotent_running(make_scheduler):
    s = make_scheduler(worker_count=1)
    evt = threading.Event()

    def block():
        evt.wait(5)

    s.register_task("block", block)
    jid = s.submit("block", idempotency_key="K2", max_retries=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.status(jid).state == "RUNNING":
            break
        time.sleep(0.005)
    with pytest.raises(DuplicateJobError):
        s.submit("block", idempotency_key="K2", max_retries=0)
    evt.set()
    s.get(jid, timeout=5)


def test_cancel(make_scheduler):
    s = make_scheduler(worker_count=1, max_queued=100)
    evt = threading.Event()

    def block():
        evt.wait(5)

    s.register_task("block", block)
    j1 = s.submit("block", max_retries=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.status(j1).state == "RUNNING":
            break
        time.sleep(0.005)
    j2 = s.submit("block", max_retries=0)
    assert s.cancel(j2) is True
    assert s.status(j2).state == "CANCELLED"
    evt.set()
    s.get(j1, timeout=5)
    assert s.status(j1).state == "COMPLETED"
    assert s.cancel(j1) is False
    with pytest.raises(JobNotFoundError):
        s.cancel("nope")


def test_executor_full(make_scheduler):
    s = make_scheduler(worker_count=1, max_queued=3)
    evt = threading.Event()

    def block():
        evt.wait(5)

    s.register_task("block", block)
    jids = [s.submit("block", max_retries=0) for _ in range(3)]
    with pytest.raises(ExecutorFullError):
        s.submit("block", max_retries=0)
    evt.set()
    for j in jids:
        s.get(j, timeout=5)


def test_invalid_params(make_scheduler):
    s = make_scheduler()

    def f():
        return 1

    with pytest.raises(InvalidJobError):
        s.submit(f, priority="high")
    with pytest.raises(InvalidJobError):
        s.submit(f, priority=True)
    with pytest.raises(InvalidJobError):
        s.submit(f, timeout=-1)
    with pytest.raises(InvalidJobError):
        s.submit(f, timeout=0)
    with pytest.raises(InvalidJobError):
        s.submit(f, idempotency_key="")
    with pytest.raises(InvalidJobError):
        s.submit(f, max_retries=-1)
    with pytest.raises(InvalidJobError):
        s.submit("missing_task")
    with pytest.raises(InvalidJobError):
        s.submit(f, object())
    with pytest.raises(InvalidJobError):
        s.submit(123)
    with pytest.raises(JobNotFoundError):
        s.status("nope")
    with pytest.raises(JobNotFoundError):
        s.get("nope")


class FakeClock:
    def __init__(self, t=0.0):
        self._t = t

    def __call__(self):
        return self._t

    def advance(self, dt):
        self._t += dt


def test_queue_aging_prevents_starvation():
    clock = FakeClock(1000.0)
    q = PriorityQueue(aging_interval=5.0, aging_step=1, now_fn=clock)
    q.push("low", 10)
    for i in range(10):
        q.push(f"high{i}", 0)
        clock.advance(1.0)
    for i in range(10):
        assert q.pop(block=False) == f"high{i}"
    assert q.qsize() == 1
    clock.advance(100.0)
    assert q.pop(block=False) == "low"
    assert q.pop(block=False) is None


def test_queue_no_aging_keeps_low_waiting():
    clock = FakeClock(0.0)
    q = PriorityQueue(aging_interval=5.0, aging_step=1, now_fn=clock)
    q.push("low", 10)
    for i in range(5):
        q.push(f"high{i}", 0)
    for i in range(5):
        assert q.pop(block=False) == f"high{i}"
    assert q.qsize() == 1
    assert q.contains("low")


def test_queue_change_priority_and_remove():
    q = PriorityQueue()
    q.push("a", 5)
    q.push("b", 3)
    q.push("c", 4)
    assert q.change_priority("a", 1) is True
    assert q.pop(block=False) == "a"
    assert q.pop(block=False) == "b"
    assert q.remove("c") is True
    assert q.pop(block=False) is None


def test_aging_scheduler_level(make_scheduler):
    clock = FakeClock(0.0)
    s = make_scheduler(
        worker_count=1,
        aging_interval=5.0,
        aging_step=1,
        now_fn=clock,
        max_queued=100,
    )
    order = []
    evt = threading.Event()

    def block():
        evt.wait(5)

    def fast(name):
        order.append(name)
        return 1

    s.register_task("block", block)
    s.register_task("fast", fast)
    filler = s.submit("block", priority=0, max_retries=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if s.status(filler).state == "RUNNING":
            break
        time.sleep(0.005)
    s.submit("fast", "low", priority=10, max_retries=0)
    clock.advance(60.0)
    for i in range(3):
        s.submit("fast", f"h{i}", priority=0, max_retries=0)
    evt.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(order) == 4:
            break
        time.sleep(0.005)
    assert order[0] == "low"
    assert set(order[1:]) == {"h0", "h1", "h2"}


def test_replay_and_snapshot(make_scheduler):
    s = make_scheduler()

    def f():
        return 1

    s.register_task("f", f)
    jid = s.submit("f", max_retries=0)
    s.get(jid, timeout=5)
    assert s.replay() >= 3
    snap = s.snapshot()
    assert snap["jobs"] >= 1
    assert os.path.exists(snap["path"])
    assert snap["lines"] >= 3
