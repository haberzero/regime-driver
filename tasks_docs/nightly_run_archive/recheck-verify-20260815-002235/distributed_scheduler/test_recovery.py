import os
import threading
from collections import Counter

from _testutil import NOOP_SLEEP, wait_status
from api import Scheduler


def _mk_func(counter, jid, block_evt=None):
    def func(job):
        counter[jid] += 1
        if block_evt is not None:
            block_evt.wait()
        return jid

    return func


def test_crash_recovery_3_jobs(tmp_path):
    wal = str(tmp_path / "wal.log")
    block_evt = threading.Event()
    exec_a = Counter()

    # Instance A: 1 succeeds, 1 gets interrupted mid-execution, 1 stays queued.
    A = Scheduler(wal, workers=1, sleep_fn=NOOP_SLEEP, base_backoff=0.0, max_attempts=1)
    A.submit("j1", _mk_func(exec_a, "j1"), idempotency_key="K1")
    A.submit("j2", _mk_func(exec_a, "j2", block_evt=block_evt))
    A.submit("j3", _mk_func(exec_a, "j3"))
    wait_status(A, "j1", "succeeded")
    wait_status(A, "j2", "running")
    assert A.status("j3") == "queued"
    # Simulate crash: abandon A without graceful shutdown. j2 stays blocked
    # forever on block_evt so A never writes another WAL record.
    assert A.replay() == 4  # 3 submits + 1 complete(j1)

    # New instance B over the same WAL.
    B = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP, base_backoff=0.0, max_attempts=1)
    exec_b = Counter()
    try:
        recovered = B.recover(func_provider=lambda job: _mk_func(exec_b, job.job_id))
        assert sorted(recovered) == ["j2", "j3"]
        assert B.status("j1") == "succeeded"
        assert B.status("j2") == "queued"
        assert B.status("j3") == "queued"
        assert B.replay() == 4

        wait_status(B, "j2", "succeeded")
        wait_status(B, "j3", "succeeded")

        # Completed idempotent job j1 was NOT re-executed; j2/j3 ran exactly once.
        assert exec_b["j1"] == 0
        assert exec_b["j2"] == 1
        assert exec_b["j3"] == 1
        assert B.stats()["recovered"] == 2
        assert B.stats()["succeeded"] == 2

        # Same idempotency key still reports a duplicate, no new execution.
        r = B.submit("j1x", _mk_func(exec_b, "j1x"), idempotency_key="K1")
        assert r.duplicate is True
        assert r.existing_job_id == "j1"
        assert exec_b["j1x"] == 0
    finally:
        B.shutdown()


def test_recover_snapshot_only_replays_incremental(tmp_path):
    wal = str(tmp_path / "wal.log")
    s = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP)
    exec_counts = Counter()
    try:
        s.submit("a", _mk_func(exec_counts, "a"))
        s.submit("b", _mk_func(exec_counts, "b"))
        wait_status(s, "a", "succeeded")
        wait_status(s, "b", "succeeded")
        s.snapshot()
        assert s.replay() == 0
        assert os.path.exists(wal + ".snapshot")
        # One job queued after the snapshot: only its records are in the WAL.
        s.submit("c", _mk_func(exec_counts, "c"))
        wait_status(s, "c", "succeeded")
        assert s.replay() == 2
    finally:
        s.shutdown()

    s2 = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP)
    exec2 = Counter()
    try:
        recovered = s2.recover(func_provider=lambda job: _mk_func(exec2, job.job_id))
        assert recovered == []  # all three already terminal
        assert s2.get("a").status == "succeeded"
        assert s2.get("b").status == "succeeded"
        assert s2.get("c").status == "succeeded"
        assert exec2["a"] == 0 and exec2["b"] == 0 and exec2["c"] == 0
    finally:
        s2.shutdown()


def test_recover_from_full_wal_no_snapshot(tmp_path):
    wal = str(tmp_path / "wal.log")
    s = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP)
    try:
        s.submit("a", lambda j: 1)
        wait_status(s, "a", "succeeded")
        assert s.replay() == 2
    finally:
        s.shutdown()

    s2 = Scheduler(wal, workers=2, sleep_fn=NOOP_SLEEP)
    try:
        recovered = s2.recover()
        assert recovered == []
        assert s2.get("a").status == "succeeded"
        assert s2.replay() == 2
    finally:
        s2.shutdown()


def test_recover_skips_torn_tail_line(tmp_path):
    wal = str(tmp_path / "wal.log")
    s = Scheduler(wal, workers=1, sleep_fn=NOOP_SLEEP)
    try:
        s.submit("a", lambda j: 1)
        wait_status(s, "a", "succeeded")
    finally:
        s.shutdown()
    # Simulate a crash mid-append: a partial trailing record without a newline.
    with open(wal, "ab") as f:
        f.write(b'{"v":1,"seq":99,"op":"submit","job":')
    s2 = Scheduler(wal, workers=1, sleep_fn=NOOP_SLEEP)
    try:
        recovered = s2.recover()
        assert recovered == []
        assert s2.get("a").status == "succeeded"
        assert s2.replay() == 2  # the torn line is skipped, not counted
        # The store keeps appending cleanly after a torn tail.
        s2.submit("b", lambda j: 2)
        wait_status(s2, "b", "succeeded")
        assert s2.get("b").status == "succeeded"
    finally:
        s2.shutdown()
