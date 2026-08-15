import threading
import time

import pytest

from api import Scheduler
from errors import DuplicateJobError, RecoveryError


def no_sleep(_):
    pass


def wait_until(predicate, timeout=10.0, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_crash_recovery_requeues_interrupted_jobs(tmp_path):
    counts = {"a": 0, "b": 0, "c": 0, "d": 0}
    gate_b = threading.Event()
    release_b = {"go": False}

    def wrap(name, fn):
        def f(*args, **kwargs):
            result = fn(*args, **kwargs)
            counts[name] += 1
            return result
        return f

    def task_a():
        return "a-ok"

    def task_b():
        if not release_b["go"]:
            gate_b.wait()
        return "b-ok"

    def task_c():
        return "c-ok"

    def task_d():
        return "d-ok"

    tasks = {
        "a": wrap("a", task_a),
        "b": wrap("b", task_b),
        "c": wrap("c", task_c),
        "d": wrap("d", task_d),
    }

    s1 = Scheduler(str(tmp_path), pool_size=1, tasks=tasks, sleep_fn=no_sleep)
    jid_d = s1.submit("d", idempotency_key="dup-key")
    jid_a = s1.submit("a")
    jid_b = s1.submit("b")
    jid_c = s1.submit("c")
    assert wait_until(lambda: s1.status(jid_d) == "completed")
    assert wait_until(lambda: s1.status(jid_a) == "completed")
    assert wait_until(lambda: s1.status(jid_b) == "running")
    assert s1.status(jid_c) == "queued"
    s1.simulate_crash()

    release_b["go"] = True

    s2 = Scheduler(str(tmp_path), pool_size=2, tasks=tasks, sleep_fn=no_sleep)
    try:
        recovered = s2.recover()
        assert recovered == 1

        assert s2.get(jid_d).state == "completed"
        assert s2.get(jid_a).state == "completed"
        assert s2.get(jid_b).state in ("queued", "running", "completed")
        assert s2.get(jid_c).state in ("queued", "running", "completed")

        for jid in (jid_a, jid_b, jid_c, jid_d):
            assert wait_until(lambda jid=jid: s2.status(jid) == "completed")

        assert s2.get(jid_b).result == "b-ok"
        assert s2.get(jid_c).result == "c-ok"

        assert counts["a"] == 1
        assert counts["b"] == 1
        assert counts["c"] == 1
        assert counts["d"] == 1

        assert s2.stats()["metrics"]["recovered"] == 1

        with pytest.raises(DuplicateJobError) as exc:
            s2.submit("d", idempotency_key="dup-key")
        assert exc.value.existing_job_id == jid_d
    finally:
        s2.close()


def test_recovery_preserves_terminal_states(tmp_path):
    def ok():
        return 1

    def bad():
        raise ValueError("x")

    with Scheduler(tmp_path, pool_size=2, tasks={"ok": ok, "bad": bad},
                   sleep_fn=no_sleep) as s:
        j_ok = s.submit("ok")
        j_bad = s.submit("bad", max_retries=0)
        assert wait_until(lambda: s.status(j_ok) == "completed")
        assert wait_until(lambda: s.status(j_bad) == "failed")

    with Scheduler(tmp_path, pool_size=2, tasks={"ok": ok, "bad": bad},
                   sleep_fn=no_sleep) as s2:
        s2.recover()
        assert s2.status(j_ok) == "completed"
        assert s2.status(j_bad) == "failed"
        assert s2.stats()["metrics"]["recovered"] == 0


def test_replay_counts_wal_records(tmp_path):
    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s:
        jids = [s.submit("t") for _ in range(2)]
        assert wait_until(lambda: all(s.status(j) == "completed" for j in jids))
        assert s.replay() == 6


def test_recover_then_submit_new_jobs(tmp_path):
    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s:
        jids = [s.submit("t") for _ in range(2)]
        assert wait_until(lambda: all(s.status(j) == "completed" for j in jids))

    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s2:
        s2.recover()
        assert s2.status(jids[0]) == "completed"
        new = s2.submit("t")
        assert wait_until(lambda: s2.status(new) == "completed")
        assert s2.get(new).result == 1


def test_snapshot_truncates_then_recovers_tail(tmp_path):
    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s:
        jids = [s.submit("t") for _ in range(3)]
        assert wait_until(lambda: all(s.status(j) == "completed" for j in jids))
        s.snapshot()
        assert s.replay() == 0
        tail = s.submit("t")
        assert wait_until(lambda: s.status(tail) == "completed")

    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}) as s2:
        s2.recover()
        assert s2.status(jids[0]) == "completed"
        assert s2.status(tail) == "completed"
        assert s2.replay() == 3


def test_recover_on_live_instance_raises(tmp_path):
    with Scheduler(tmp_path, tasks={"t": lambda: 1}) as s:
        s.recover()
        s.submit("t")
        with pytest.raises(RecoveryError):
            s.recover()
