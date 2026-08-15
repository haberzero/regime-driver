import threading
import time

import pytest

from errors import DuplicateJobError


def wait_terminal(scheduler, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = scheduler.status(job_id)
        if st.state in ("COMPLETED", "FAILED", "CANCELLED"):
            return st
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} not terminal: {scheduler.status(job_id)}")


def test_crash_recovery_three_jobs(make_scheduler):
    executions = []
    blocker_runs = []
    plain_runs = []
    release = threading.Event()

    def idem_fn():
        executions.append(1)
        return "done"

    def blocker_fn():
        release.wait()
        return "blocked"

    def plain_fn():
        plain_runs.append(1)
        return "plain"

    sA = make_scheduler(worker_count=1, max_queued=100)
    sA.register_task("idem", idem_fn)
    sA.register_task("blocker", blocker_fn)
    sA.register_task("plain", plain_fn)

    j1 = sA.submit("idem", idempotency_key="K1", max_retries=0)
    j2 = sA.submit("blocker", max_retries=0)
    j3 = sA.submit("plain", max_retries=0)

    deadline = time.time() + 5
    while time.time() < deadline:
        if (
            sA.status(j1).state == "COMPLETED"
            and sA.status(j2).state == "RUNNING"
            and sA.status(j3).state == "QUEUED"
        ):
            break
        time.sleep(0.005)
    assert sA.status(j1).state == "COMPLETED"
    assert sA.status(j2).state == "RUNNING"
    assert sA.status(j3).state == "QUEUED"

    sA.shutdown(wait=False)

    lines_before = sA.replay()
    assert lines_before == 6

    def fast_blocker():
        blocker_runs.append(1)
        return "blocked-again"

    sB = make_scheduler(worker_count=2, max_queued=100)
    sB.register_task("idem", idem_fn)
    sB.register_task("blocker", fast_blocker)
    sB.register_task("plain", plain_fn)

    res = sB.recover()
    assert res["jobs"] == 3
    assert res["recovered"] == 1

    for j in (j1, j2, j3):
        wait_terminal(sB, j)

    assert sB.status(j1).state == "COMPLETED"
    assert sB.status(j2).state == "COMPLETED"
    assert sB.status(j3).state == "COMPLETED"

    assert len(executions) == 1
    assert len(blocker_runs) == 1
    assert len(plain_runs) == 1

    assert sB.stats()["recovered"] == 1
    assert sB.stats()["submitted"] == 0

    with pytest.raises(DuplicateJobError):
        sB.submit("idem", idempotency_key="K1", max_retries=0)

    assert sB.replay() == 10


def test_recover_empty(make_scheduler):
    s = make_scheduler(worker_count=1)
    res = s.recover()
    assert res["jobs"] == 0
    assert res["recovered"] == 0
    assert s.replay() == 0


def test_recovery_idempotent_not_double_executed_after_crash(make_scheduler):
    executions = []

    def idem_fn():
        executions.append(1)
        return "ok"

    sA = make_scheduler(worker_count=1, max_queued=100)
    sA.register_task("idem", idem_fn)
    jid = sA.submit("idem", idempotency_key="KX", max_retries=0)
    wait_terminal(sA, jid)
    assert sA.status(jid).state == "COMPLETED"
    assert len(executions) == 1
    sA.shutdown(wait=False)

    sB = make_scheduler(worker_count=1, max_queued=100)
    sB.register_task("idem", idem_fn)
    res = sB.recover()
    assert res["recovered"] == 0
    assert sB.status(jid).state == "COMPLETED"
    assert len(executions) == 1
    with pytest.raises(DuplicateJobError):
        sB.submit("idem", idempotency_key="KX", max_retries=0)

