"""Top-level facade composing store, priority queue, executor, idempotency,
recovery and metrics behind a single thread-safe Scheduler.

Lock ordering is strict and unidirectional: the scheduler lock is acquired
before any store or priority-queue lock, and the priority queue / executor
never hold their locks while calling back into the scheduler. Public methods
validate arguments and raise the errors defined in ``errors``.
"""

import threading
import time
import uuid
from pathlib import Path

from errors import (
    ExecutorFullError,
    InvalidJobError,
    JobNotFoundError,
    RecoveryError,
)
from executor import Executor
from idempotency import Idempotency
from job_store import (
    QUEUED,
    RUNNING,
    TERMINAL,
    Job,
    JobStore,
)
from metrics import Metrics
from priority_queue import PriorityQueue
from recovery import Recovery


class Scheduler:
    def __init__(self, wal_path=None, data_dir=None, num_workers=4, clock=time.time,
                 sleep=time.sleep, rng=None, base_backoff=0.05, max_backoff=1.0,
                 boost_interval=1.0, boost_step=1, max_boost=None, max_pending=None,
                 auto_start=True):
        if wal_path is None:
            base = Path(data_dir) if data_dir else Path(".")
            wal_path = base / "scheduler.wal"
        self._wal_path = Path(wal_path)
        self._clock = clock
        self._sleep = sleep
        self._store = JobStore(self._wal_path)
        self._idem = Idempotency(self._store)
        self._pq = PriorityQueue(
            clock=clock, boost_interval=boost_interval,
            boost_step=boost_step, max_boost=max_boost)
        self._metrics = Metrics()
        self._executor = Executor(
            num_workers, callbacks=self, sleep=sleep, clock=clock,
            base_backoff=base_backoff, max_backoff=max_backoff, rng=rng,
            max_pending=max_pending)
        self._recovery = Recovery(self._store, self._pq, self._metrics, clock=clock)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._started = False
        self._dispatcher_thread = None
        if auto_start:
            self.start()

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop.clear()
            self._executor.start()
            self._dispatcher_thread = threading.Thread(target=self._dispatcher, daemon=True)
            self._dispatcher_thread.start()

    def close(self):
        self._stop.set()
        self._executor.stop()
        if self._dispatcher_thread is not None:
            self._dispatcher_thread.join(timeout=1.0)

    def crash(self):
        """Simulate a crash: stop all scheduling/write activity immediately."""
        self.close()

    # -- public API --------------------------------------------------------

    def submit(self, fn, priority=0, timeout=10.0, max_retries=0, idempotency_key=None):
        self._validate_submit(fn, priority, timeout, max_retries, idempotency_key)
        with self._lock:
            if self._stop.is_set():
                raise RecoveryError("scheduler is stopped")
            self._idem.check_submit(idempotency_key)
            job = Job(
                job_id=uuid.uuid4().hex,
                fn=fn,
                priority=priority,
                timeout=timeout,
                max_retries=max_retries,
                idempotency_key=idempotency_key,
                created_at=self._clock(),
            )
            self._store.submit(job)
            self._pq.put(job.job_id, job.priority)
            self._metrics.inc("submitted")
            return job.job_id

    def get(self, job_id):
        with self._lock:
            job = self._store.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def status(self, job_id):
        return self.get(job_id).state

    def cancel(self, job_id):
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            if job.state in TERMINAL:
                return False
            self._store.mark_canceled(job_id)
            if job.state == QUEUED:
                self._pq.remove(job_id)
            return True

    def priority(self, job_id, new_priority):
        if isinstance(new_priority, bool) or not isinstance(new_priority, int):
            raise InvalidJobError("new_priority must be an int")
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            self._store.set_priority(job_id, new_priority)
            if job.state == QUEUED:
                self._pq.update_priority(job_id, new_priority)

    def stats(self):
        with self._lock:
            running = sum(1 for j in self._store.all() if j.state == RUNNING)
            return {
                "metrics": self._metrics.snapshot(),
                "total": len(self._store),
                "running": running,
                "queued": len(self._pq),
            }

    def replay(self):
        return self._store.count_records()

    def snapshot(self):
        with self._lock:
            self._store.snapshot(self._metrics.snapshot())

    def recover(self, fn_provider=None):
        with self._lock:
            if self._started and not self._stop.is_set():
                raise RecoveryError("recover() must be called on a stopped scheduler")
            counts = self._store.replay()
            self._metrics.set_all(counts)
            return self._recovery.apply(fn_provider)

    # -- dispatch loop -----------------------------------------------------

    def _dispatcher(self):
        while not self._stop.is_set():
            self._executor.wait_for_capacity(self._stop)
            if self._stop.is_set():
                return
            job_id = self._pq.pop(self._stop)
            if job_id is None:
                return
            with self._lock:
                job = self._store.get(job_id)
                if job is None or job.state != QUEUED:
                    continue
                try:
                    self._executor.dispatch(job)
                except ExecutorFullError:
                    self._pq.put(job_id, job.priority)

    # -- executor callbacks ------------------------------------------------

    def on_start(self, job):
        with self._lock:
            if self._stop.is_set():
                return False
            current = self._store.get(job.job_id)
            if current is None or current.state != QUEUED:
                return False
            self._store.mark_started(job.job_id)
            return True

    def on_succeeded(self, job):
        with self._lock:
            if self._stop.is_set():
                return
            current = self._store.get(job.job_id)
            if current is None or current.state != RUNNING:
                return
            self._store.mark_succeeded(job.job_id)
            self._metrics.inc("succeeded")

    def on_failed(self, job, exc):
        self._handle_failure(job, exc, timed_out=False)

    def on_timeout(self, job, exc):
        self._handle_failure(job, exc, timed_out=True)

    def _handle_failure(self, job, exc, timed_out):
        with self._lock:
            if self._stop.is_set():
                return
            current = self._store.get(job.job_id)
            if current is None or current.state != RUNNING:
                return
            if timed_out:
                self._store.mark_timeout(job.job_id)
                self._metrics.inc("deadline_hit")
            if current.attempts < current.max_retries + 1:
                self._store.mark_retry(job.job_id)
                self._metrics.inc("retried")
                self._retry_later(current)
            else:
                self._store.mark_failed(job.job_id, str(exc))
                self._metrics.inc("failed")

    def _retry_later(self, job):
        delay = self._executor.backoff_for(job.attempts)

        def _do():
            self._sleep(delay)
            with self._lock:
                if self._stop.is_set():
                    return
                current = self._store.get(job.job_id)
                if current is None or current.state != QUEUED:
                    return
                self._pq.put(current.job_id, current.priority)

        threading.Thread(target=_do, daemon=True).start()

    # -- validation --------------------------------------------------------

    @staticmethod
    def _validate_submit(fn, priority, timeout, max_retries, idempotency_key):
        if not callable(fn):
            raise InvalidJobError("fn must be callable")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise InvalidJobError("priority must be an int (smaller = higher priority)")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise InvalidJobError("timeout must be a positive number")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise InvalidJobError("max_retries must be a non-negative int")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise InvalidJobError("idempotency_key must be a non-empty string")
