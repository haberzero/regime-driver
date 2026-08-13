"""Crash-recovery tests: replay WAL in a fresh instance, reschedule
interrupted jobs, and never re-execute completed idempotent jobs."""

import threading

import pytest

from api import Scheduler
from errors import DuplicateJobError
from job_store import QUEUED, RUNNING, SUCCEEDED
from test_helpers import wait_until


def test_crash_recovery_reschedules_interrupted_and_keeps_done(tmp_path):
    wal = tmp_path / "w.log"
    blocked = threading.Event()
    done_runs = []
    interrupted_runs = []
    queued_runs = []

    # ---- phase 1: live scheduler --------------------------------------
    s1 = Scheduler(wal_path=wal, num_workers=1)
    try:
        j_done = s1.submit(lambda: done_runs.append(1) or "done",
                           idempotency_key="key-done")
        j_interrupted = s1.submit(lambda: interrupted_runs.append(1) or blocked.wait(60),
                                  max_retries=1, timeout=10.0)
        j_queued = s1.submit(lambda: queued_runs.append(1) or "queued",
                             timeout=10.0)

        assert wait_until(lambda: s1.status(j_done) == SUCCEEDED)
        assert wait_until(lambda: s1.status(j_interrupted) == RUNNING)
        # single worker is stuck on the interrupted job; j_queued stays queued
        assert s1.status(j_queued) == QUEUED
        assert done_runs == [1]

        s1.crash()
    finally:
        blocked.set()  # release the phase-1 runaway thread (it must not write)

    # ---- phase 2: fresh instance recovers from WAL ----------------------
    s2 = Scheduler(wal_path=wal, num_workers=1, auto_start=False)
    try:
        provider = {
            j_done: lambda: done_runs.append(2) or "done-again",
            j_interrupted: lambda: interrupted_runs.append(2) or "resumed",
            j_queued: lambda: queued_runs.append(2) or "queued-again",
            "key-done": None,
        }

        recovered = s2.recover(fn_provider=provider)

        # All three committed jobs are back; done stays done, interrupted is
        # queued for rescheduling, queued stays queued.
        assert recovered == 1
        assert s2.status(j_done) == SUCCEEDED
        assert s2.status(j_interrupted) == QUEUED
        assert s2.status(j_queued) == QUEUED
        assert s2.stats()["total"] == 3
        assert s2.stats()["metrics"]["recovered"] == 1
        assert s2.stats()["metrics"]["submitted"] == 3
        assert s2.stats()["metrics"]["succeeded"] == 1

        # Duplicate idempotency key still detected after replay.
        with pytest.raises(DuplicateJobError):
            s2.submit(lambda: None, idempotency_key="key-done")

        # Resume: interrupted + queued jobs re-execute to completion.
        s2.start()
        assert wait_until(lambda: s2.status(j_interrupted) == SUCCEEDED)
        assert wait_until(lambda: s2.status(j_queued) == SUCCEEDED)

        # Interrupted job was rescheduled exactly once after recovery.
        assert interrupted_runs == [1, 2]
        # Queued job never ran in phase 1 (worker was stuck); ran once after recovery.
        assert queued_runs == [2]
        # Completed idempotent job was never re-executed.
        assert done_runs == [1]
        assert s2.stats()["metrics"]["succeeded"] == 3
    finally:
        s2.close()


def test_recovery_replays_metrics_from_wal(tmp_path):
    wal = tmp_path / "w.log"
    s1 = Scheduler(wal_path=wal, num_workers=1)
    try:
        s1.submit(lambda: None, max_retries=0)
        s1.submit(lambda: (_ for _ in ()).throw(RuntimeError("boom")), max_retries=0)
        assert wait_until(lambda: s1.stats()["metrics"]["succeeded"] == 1)
        assert wait_until(lambda: s1.stats()["metrics"]["failed"] == 1)
        s1.crash()
    finally:
        s1.close()

    s2 = Scheduler(wal_path=wal, num_workers=1, auto_start=False)
    try:
        s2.recover(fn_provider={})
        metrics = s2.stats()["metrics"]
        assert metrics["submitted"] == 2
        assert metrics["succeeded"] == 1
        assert metrics["failed"] == 1
        assert metrics["recovered"] == 0
    finally:
        s2.close()


def test_recovery_tolerates_torn_trailing_wal_line(tmp_path):
    wal = tmp_path / "w.log"
    s1 = Scheduler(wal_path=wal, auto_start=False)
    jid = s1.submit(lambda: None)
    s1.close()

    with open(wal, "a") as fh:
        fh.write('{"type":"submit","sn":99,"id":"par')  # torn partial record

    s2 = Scheduler(wal_path=wal, auto_start=False)
    s2.recover(fn_provider={})
    assert s2.stats()["total"] == 1
    assert s2.status(jid) == QUEUED
