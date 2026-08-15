import json
import random
import threading
import time
import uuid

from errors import ExecutorFullError, InvalidJobError, RecoveryError
from executor import Executor
from idempotency import IdempotencyRegistry
from job_store import JobRecord, JobStore
from metrics import Metrics
from priority_queue import PriorityQueue
import recovery

_TERMINAL_STATES = ("completed", "failed", "cancelled")


class Scheduler:
    """Top-level facade tying the priority queue, executor, store, idempotency
    and metrics together.

    Jobs are submitted to the priority queue immediately (submit never waits
    for a free worker); a single dispatcher thread moves them to the fixed
    worker pool as slots free up. On a crash a fresh Scheduler over the same
    directory recovers all committed jobs from snapshot + WAL.
    """

    def __init__(self, work_dir, *, pool_size=4, max_retries=2, default_timeout=None,
                 base_backoff=0.5, max_backoff=60.0, aging_interval=5.0,
                 clock=time.monotonic, sleep_fn=time.sleep, random_fn=random.uniform,
                 tasks=None):
        self._store = JobStore(work_dir)
        self._metrics = Metrics()
        self._idempotency = IdempotencyRegistry(self._store)
        self._pq = PriorityQueue(aging_interval=aging_interval, clock=clock)
        self._tasks = dict(tasks or {})
        self._default_max_retries = max_retries
        self._default_timeout = default_timeout
        self._executor = Executor(
            pool_size=pool_size,
            store=self._store,
            metrics=self._metrics,
            sleep_fn=sleep_fn,
            random_fn=random_fn,
            base_backoff=base_backoff,
            max_backoff=max_backoff,
            on_idle=self._wake_dispatcher,
        )
        self._shutdown = threading.Event()
        self._cond = threading.Condition()
        self._dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher.start()

    # -- lifecycle -----------------------------------------------------------

    def close(self):
        self._shutdown.set()
        with self._cond:
            self._cond.notify_all()
        if self._dispatcher.is_alive():
            self._dispatcher.join(timeout=2.0)
        self._executor.shutdown()
        self._store.close()

    def simulate_crash(self):
        """Abruptly stop the scheduler without completing running jobs.

        The WAL is fsynced on every event, so a new Scheduler over the same
        directory can recover all committed jobs afterwards.
        """
        self._shutdown.set()
        with self._cond:
            self._cond.notify_all()
        if self._dispatcher.is_alive():
            self._dispatcher.join(timeout=2.0)
        self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # -- public API ----------------------------------------------------------

    def submit(self, task, *args, priority=0, idempotency_key=None, timeout=None,
               max_retries=None, **kwargs):
        self._validate_task(task)
        if not isinstance(priority, int):
            raise InvalidJobError(f"priority must be an int, got {type(priority).__name__}")
        if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
            raise InvalidJobError(f"timeout must be a positive number or None, got {timeout!r}")
        if max_retries is None:
            max_retries = self._default_max_retries
        if not isinstance(max_retries, int) or max_retries < 0:
            raise InvalidJobError(f"max_retries must be a non-negative int, got {max_retries!r}")
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key):
            raise InvalidJobError("idempotency_key must be a non-empty string or None")
        try:
            json.dumps({"args": list(args), "kwargs": kwargs})
        except TypeError as exc:
            raise InvalidJobError(f"args/kwargs must be JSON-serializable: {exc}") from exc
        if timeout is None:
            timeout = self._default_timeout
        job = JobRecord(
            job_id=uuid.uuid4().hex,
            task=task,
            priority=priority,
            idempotency_key=idempotency_key,
            args=list(args),
            kwargs=dict(kwargs),
            timeout=timeout,
            max_retries=max_retries,
            created_at=time.monotonic(),
        )
        self._store.add(job, precheck=self._idempotency.precheck)
        self._pq.push(job)
        self._metrics.inc("submitted")
        with self._cond:
            self._cond.notify_all()
        return job.job_id

    def get(self, job_id):
        return self._store.get(job_id)

    def status(self, job_id):
        return self._store.get(job_id).state

    def cancel(self, job_id):
        job = self._store.get(job_id)
        if job.state in _TERMINAL_STATES:
            return False
        was_queued = job.state == "queued"
        changed = self._store.mark_cancelled(job_id)
        if was_queued:
            self._pq.remove(job_id)
        return changed

    def set_priority(self, job_id, priority):
        if not isinstance(priority, int):
            raise InvalidJobError(f"priority must be an int, got {type(priority).__name__}")
        job = self._store.get(job_id)
        if job.state in _TERMINAL_STATES:
            return False
        changed = self._store.set_priority(job_id, priority)
        if changed and job.state == "queued":
            self._pq.update_priority(self._store.get(job_id))
        return changed

    def stats(self):
        counts = {}
        for record in self._store.all_jobs().values():
            counts[record.state] = counts.get(record.state, 0) + 1
        return {
            "metrics": self._metrics.snapshot(),
            "jobs": counts,
            "queued": len(self._pq),
        }

    def recover(self):
        """Recover committed jobs from snapshot + WAL on a fresh instance.

        Running jobs are rolled back to queued and re-dispatched; terminal
        jobs (including completed idempotent jobs) are preserved untouched.
        Returns the number of interrupted jobs rolled back to queued.
        """
        if not self._store.is_empty():
            raise RecoveryError(
                "recover() must be called on a fresh instance before any jobs "
                "are loaded or submitted"
            )
        rolled, queued = recovery.recover(self._store)
        for record in queued:
            self._pq.push(record)
        if rolled:
            self._metrics.inc("recovered", len(rolled))
        with self._cond:
            self._cond.notify_all()
        return len(rolled)

    def replay(self):
        """Number of WAL records currently present."""
        return self._store.replay()

    def snapshot(self):
        self._store.snapshot()

    # -- internals -----------------------------------------------------------

    def _validate_task(self, task):
        if not isinstance(task, str) or not task:
            raise InvalidJobError("task must be a non-empty registered task name")
        if task not in self._tasks:
            raise InvalidJobError(f"unknown task: {task!r}")

    def _wake_dispatcher(self):
        with self._cond:
            self._cond.notify_all()

    def _resolve(self, job):
        return self._tasks[job.task]

    def _dispatch_loop(self):
        while not self._shutdown.is_set():
            with self._cond:
                self._cond.wait_for(
                    lambda: self._shutdown.is_set()
                    or (not self._pq.is_empty() and self._executor.free_slots() > 0)
                )
                if self._shutdown.is_set():
                    break
                if self._pq.is_empty() or self._executor.free_slots() == 0:
                    continue
                job = self._pq.pop()
                if job is None:
                    continue
                try:
                    self._executor.submit(job, self._resolve)
                except ExecutorFullError:
                    self._pq.push(job)
