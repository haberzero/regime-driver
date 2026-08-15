import threading
import time

from api import Scheduler
from errors import DuplicateJobError

TERMINAL_STATES = ("completed", "failed", "cancelled")


def no_sleep(_):
    pass


def wait_until(predicate, timeout=10.0, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_concurrent_submit_cancel_priority(tmp_path):
    def work(n, i):
        return n + i

    with Scheduler(tmp_path, pool_size=4, tasks={"t": work}, sleep_fn=no_sleep) as s:
        barrier = threading.Barrier(9)
        errors = []
        job_ids = []

        def worker(n):
            try:
                barrier.wait()
                for i in range(40):
                    jid = s.submit("t", n, i, priority=i % 5)
                    job_ids.append(jid)
                    if i % 3 == 0:
                        s.cancel(jid)
                    if i % 2 == 0:
                        s.set_priority(jid, i % 5)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=20)
        assert not errors
        assert all(not thread.is_alive() for thread in threads)

        for jid in job_ids:
            assert wait_until(lambda jid=jid: s.status(jid) in TERMINAL_STATES)

        states = set(record.state for record in s._store.all_jobs().values())
        assert states <= set(TERMINAL_STATES)
        assert len(job_ids) == 8 * 40


def test_concurrent_duplicate_idempotency_key(tmp_path):
    with Scheduler(tmp_path, pool_size=4, tasks={"t": lambda: 1}, sleep_fn=no_sleep) as s:
        barrier = threading.Barrier(9)
        successes = []
        duplicates = []
        errors = []
        job_ids = []

        def worker(n):
            try:
                barrier.wait()
                try:
                    jid = s.submit("t", idempotency_key="shared")
                    successes.append(jid)
                except DuplicateJobError as exc:
                    duplicates.append(exc)
                jid2 = s.submit("t", idempotency_key=f"k{n}")
                job_ids.append(jid2)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=20)
        assert not errors
        assert len(successes) == 1
        assert len(duplicates) == 7
        assert len(job_ids) == 8

        keyed = s._store.get_by_key("shared")
        assert keyed is not None
        assert successes[0] == keyed.job_id
        assert all(exc.existing_job_id == keyed.job_id for exc in duplicates)

        for jid in job_ids + successes:
            assert wait_until(lambda jid=jid: s.status(jid) in TERMINAL_STATES)


def test_concurrent_cancel_of_unknown_id_is_safe(tmp_path):
    with Scheduler(tmp_path, pool_size=2, tasks={"t": lambda: 1}, sleep_fn=no_sleep) as s:
        barrier = threading.Barrier(9)
        errors = []

        def worker(n):
            try:
                barrier.wait()
                jid = s.submit("t")
                for _ in range(20):
                    s.cancel(jid)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=20)
        assert not errors
