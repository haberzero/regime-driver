import threading

from _testutil import NOOP_SLEEP
from api import Scheduler
from clock import Clock
from priority_queue import PriorityQueue


def test_8_threads_concurrent_ops_no_corruption(tmp_path):
    s = Scheduler(
        str(tmp_path / "wal.log"),
        workers=8,
        sleep_fn=NOOP_SLEEP,
        base_backoff=0.0,
        max_attempts=2,
    )
    N_THREADS = 8
    N_JOBS = 20
    barrier = threading.Barrier(N_THREADS)
    errors = []
    errors_lock = threading.Lock()

    def worker(tid):
        try:
            barrier.wait()
            for i in range(N_JOBS):
                jid = f"w{tid}-{i}"
                s.submit(jid, lambda job: job.job_id, priority=i % 5)
                if i % 3 == 0:
                    s.cancel(jid)
                if i % 4 == 0:
                    s.change_priority(jid, (i + 1) % 5)
                s.status(jid)
        except Exception as e:  # noqa: BLE001 - record any leak for the assertion
            with errors_lock:
                errors.append((tid, repr(e)))

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"unexpected exceptions leaked from threads: {errors}"

    s.shutdown(wait=True)
    stats = s.stats()
    assert stats["total"] == N_THREADS * N_JOBS
    assert stats["submitted"] == N_THREADS * N_JOBS
    # every job reached a terminal state, no corruption
    assert stats["queued"] == 0
    assert stats["running"] == 0
    assert stats["cancelled"] + stats["succeeded"] + stats["failed"] == stats["total"]
    records, _ = s._store.read_records()
    assert len(records) >= N_THREADS * N_JOBS


def test_concurrent_submit_same_idempotency_key(tmp_path):
    s = Scheduler(str(tmp_path / "wal.log"), workers=8, sleep_fn=NOOP_SLEEP)
    N_THREADS = 8
    barrier = threading.Barrier(N_THREADS)
    results = []
    results_lock = threading.Lock()
    errors = []

    def worker(tid):
        try:
            barrier.wait()
            r = s.submit(f"job-{tid}", lambda job: tid, idempotency_key="SAME-KEY")
            with results_lock:
                results.append(r)
        except Exception as e:  # noqa: BLE001
            errors.append((tid, repr(e)))

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    s.shutdown(wait=True)

    created = [r for r in results if not r.duplicate]
    duplicates = [r for r in results if r.duplicate]
    assert len(created) == 1
    assert len(duplicates) == N_THREADS - 1
    for r in duplicates:
        assert r.existing_job_id == created[0].job_id
    stats = s.stats()
    assert stats["submitted"] == 1
    assert stats["total"] == 1
    assert stats["succeeded"] == 1


def test_aging_guarantees_low_priority_under_flood(tmp_path):
    t = [0.0]
    q = PriorityQueue(aging_threshold=5.0, clock=Clock(lambda: t[0]))
    q.put(10, "low", enqueued_at=0.0)
    for i in range(200):
        q.put(0, f"high{i}", enqueued_at=t[0])
        t[0] += 0.01
    # Without aging the flood would starve "low" forever; aging promotes it.
    t[0] = 10.0
    assert q.pop() == (1, "low")


def test_strict_priority_starves_low_without_aging(tmp_path):
    t = [0.0]
    q = PriorityQueue(aging_threshold=None, clock=Clock(lambda: t[0]))
    q.put(10, "low", enqueued_at=0.0)
    for i in range(200):
        q.put(0, f"high{i}", enqueued_at=t[0])
        t[0] += 0.01
    t[0] = 10.0
    for i in range(200):
        seq, jid = q.pop()
        assert jid == f"high{i}"
    assert q.pop() == (1, "low")
