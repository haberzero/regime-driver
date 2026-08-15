import threading
import time

from errors import DuplicateJobError


def wait_all_terminal(scheduler, job_ids, timeout=15.0):
    deadline = time.time() + timeout
    pending = set(job_ids)
    while time.time() < deadline:
        for jid in list(pending):
            if _terminal(scheduler.status(jid).state):
                pending.discard(jid)
        if not pending:
            return
        time.sleep(0.005)
    raise AssertionError(f"jobs not terminal: {sorted(pending)}")


def _terminal(state):
    return state in ("COMPLETED", "FAILED", "CANCELLED")


def noop():
    pass


def test_barrier_concurrent_submit_cancel_priority(make_scheduler):
    s = make_scheduler(worker_count=4, max_queued=100000)
    n_threads = 8
    n_each = 20
    barrier = threading.Barrier(n_threads)
    errors = []
    job_ids = []
    ids_lock = threading.Lock()

    def worker(_):
        try:
            barrier.wait(timeout=10)
            for k in range(n_each):
                jid = s.submit(noop, priority=k % 5, max_retries=0)
                with ids_lock:
                    job_ids.append(jid)
                if k % 2 == 0:
                    s.change_priority(jid, (k + 1) % 5)
                if k % 3 == 0:
                    s.cancel(jid)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"threads leaked exceptions: {errors}"
    assert len(job_ids) == n_threads * n_each

    wait_all_terminal(s, job_ids)

    statuses = [s.status(j) for j in job_ids]
    assert all(_terminal(st.state) for st in statuses)
    cancelled = sum(1 for st in statuses if st.state == "CANCELLED")
    stats = s.stats()
    assert stats["submitted"] == n_threads * n_each
    assert stats["succeeded"] + stats["failed"] + cancelled == n_threads * n_each
    assert stats["queued"] == 0
    assert stats["running"] == 0


def test_concurrent_same_idempotency_key(make_scheduler):
    s = make_scheduler(worker_count=2)
    counter = []

    def idem_fn():
        counter.append(1)
        return "x"

    s.register_task("idem_fn", idem_fn)
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    outcomes = []

    def worker(_):
        barrier.wait(timeout=10)
        try:
            s.submit("idem_fn", idempotency_key="shared", max_retries=0)
            outcomes.append("submitted")
        except DuplicateJobError:
            outcomes.append("duplicate")
        except Exception as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert outcomes.count("submitted") == 1
    assert outcomes.count("duplicate") == n_threads - 1
    assert all(o in ("submitted", "duplicate") for o in outcomes)
    assert s.stats()["submitted"] == 1

    deadline = time.time() + 5
    while time.time() < deadline:
        if s.stats()["succeeded"] == 1:
            break
        time.sleep(0.005)
    assert s.stats()["succeeded"] == 1
    assert len(counter) == 1
