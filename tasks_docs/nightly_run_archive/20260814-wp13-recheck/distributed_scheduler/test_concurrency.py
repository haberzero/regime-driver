"""Concurrency tests: 8 threads racing submit + cancel + priority changes
with a start barrier -- no data corruption and no leaked exceptions."""

import threading

from api import Scheduler
from test_helpers import wait_until


def test_8_threads_submit_cancel_priority_no_corruption(tmp_path):
    num_threads = 8
    jobs_per_thread = 8
    release = threading.Event()
    barrier = threading.Barrier(num_threads + 1)
    quick_counter = {"n": 0}
    counter_lock = threading.Lock()
    errors = []
    all_ids = []
    ids_lock = threading.Lock()

    def quick_fn():
        with counter_lock:
            quick_counter["n"] += 1
        return "ok"

    def blocked_fn():
        release.wait(60)
        return "blocked-done"

    def worker(t_idx):
        try:
            barrier.wait(timeout=10)  # start gate
            sched = Scheduler(
                wal_path=tmp_path / "w-{}.log".format(t_idx),
                num_workers=2, base_backoff=0.01, max_backoff=0.02,
            )
            try:
                for i in range(jobs_per_thread):
                    jid = sched.submit(quick_fn, timeout=5.0)
                    with ids_lock:
                        all_ids.append(jid)
                    if i % 2 == 0:
                        sched.priority(jid, i)  # arbitrary priority change
                # A few jobs cancelled while queued (blocking fn guarantees
                # they cannot run before we cancel).
                cancel_ids = []
                for _ in range(2):
                    cid = sched.submit(blocked_fn, timeout=30.0)
                    cancel_ids.append(cid)
                    with ids_lock:
                        all_ids.append(cid)
                for cid in cancel_ids:
                    assert sched.cancel(cid) is True
                assert wait_until(lambda: sched.stats()["metrics"]["succeeded"]
                                  == jobs_per_thread)
                for cid in cancel_ids:
                    assert sched.status(cid) == "canceled"
            finally:
                sched.close()
        except BaseException as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)
        finally:
            barrier.wait(timeout=10)  # done gate

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    barrier.wait(timeout=10)  # release start gate
    barrier.wait(timeout=10)  # wait for all workers to reach the done gate
    for t in threads:
        t.join(timeout=30)
    release.set()

    assert errors == [], "worker threads leaked exceptions: {!r}".format(errors)
    expected_total = num_threads * (jobs_per_thread + 2)
    assert len(all_ids) == expected_total
    assert len(set(all_ids)) == expected_total, "duplicate job ids leaked"
    assert quick_counter["n"] == num_threads * jobs_per_thread
