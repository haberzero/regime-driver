import copy
import json
import threading
import time
from typing import Callable, NamedTuple, Optional

from clock import Clock
from errors import DuplicateJobError, ExecutorFullError, InvalidJobError, JobNotFoundError
from executor import Executor
from idempotency import IdempotencyIndex
from job_store import Job, JobStore
from metrics import Metrics
from priority_queue import PriorityQueue
from recovery import Recovery


class SubmitResult(NamedTuple):
    job_id: str
    duplicate: bool = False
    existing_job_id: Optional[str] = None


class Scheduler:
    """Top-level facade composing JobStore, PriorityQueue, Executor,
    IdempotencyIndex, Recovery and Metrics.

    submit() is durable-first: the WAL record is fsync'd before the job is
    enqueued and before submit returns, so a caller-acknowledged job is never
    lost. A background dispatch loop pops the priority queue and feeds the
    executor, applying backpressure when the executor is at capacity
    (ExecutorFullError never surfaces through Scheduler.submit).
    """

    def __init__(
        self,
        wal_path: str,
        workers: int = 4,
        aging_threshold: float = 5.0,
        timeout: Optional[float] = None,
        max_attempts: int = 3,
        base_backoff: float = 0.1,
        cap_backoff: float = 30.0,
        queue_size: int = 1024,
        fsync: bool = True,
        sleep_fn=time.sleep,
        rng=None,
        clock: Clock = None,
        auto_start: bool = True,
    ):
        self._wal_path = wal_path
        self._lock = threading.Lock()
        self._clock = clock if clock is not None else Clock()
        self._metrics = Metrics()
        self._store = JobStore(wal_path, fsync=fsync)
        self._queue = PriorityQueue(aging_threshold=aging_threshold, clock=self._clock)
        self._idem = IdempotencyIndex()
        self._executor = Executor(
            workers=workers,
            queue_size=queue_size,
            base_backoff=base_backoff,
            cap_backoff=cap_backoff,
            max_attempts=max_attempts,
            sleep_fn=sleep_fn,
            rng=rng,
            on_complete=self._on_complete,
            clock=self._clock,
        )
        self._recovery = Recovery(self._store, self._queue, self._idem, self._metrics, clock=self._clock)
        self._default_timeout = timeout
        self._default_max_attempts = max_attempts
        self._shutdown = False
        self._dispatch_cond = threading.Condition()
        self._dispatch_thread = None
        if auto_start:
            self.start()

    def start(self) -> None:
        if self._dispatch_thread is None:
            self._dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
            self._dispatch_thread.start()

    def __enter__(self) -> "Scheduler":
        return self

    def __exit__(self, *exc) -> None:
        self.shutdown()

    # ------------------------------------------------------------------ API

    def submit(
        self,
        job_id: str,
        func: Callable,
        payload=None,
        priority: int = 0,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_attempts: Optional[int] = None,
    ) -> SubmitResult:
        if not isinstance(job_id, str) or not job_id:
            raise InvalidJobError("job_id must be a non-empty string")
        if not callable(func):
            raise InvalidJobError("func must be callable")
        if not isinstance(priority, int):
            raise InvalidJobError("priority must be an integer")
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key):
            raise InvalidJobError("idempotency_key must be a non-empty string or None")
        if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
            raise InvalidJobError("timeout must be a positive number or None")
        if max_attempts is None:
            max_attempts = self._default_max_attempts
        if not isinstance(max_attempts, int) or max_attempts <= 0:
            raise InvalidJobError("max_attempts must be a positive integer")
        try:
            json.dumps(payload)
        except (TypeError, ValueError):
            raise InvalidJobError("payload must be JSON-serializable")

        with self._lock:
            if idempotency_key is not None:
                existing = self._idem.lookup(idempotency_key)
                if existing is not None:
                    return SubmitResult(job_id=existing, duplicate=True, existing_job_id=existing)
            if self._store.get(job_id) is not None:
                raise DuplicateJobError(f"job_id {job_id!r} already exists")
            now = self._clock()
            job = Job(
                job_id=job_id,
                priority=priority,
                payload=payload,
                idempotency_key=idempotency_key,
                timeout=timeout if timeout is not None else self._default_timeout,
                max_attempts=max_attempts,
                created_at=now,
                enqueued_at=now,
                func=func,
            )
            self._store.submit_job(job)
            if idempotency_key is not None:
                self._idem.register(idempotency_key, job_id)
            self._metrics.inc("submitted")
            self._queue.put(priority, job_id, enqueued_at=now)
        self._wake_dispatch()
        return SubmitResult(job_id=job_id)

    def get(self, job_id: str) -> Job:
        job = self._store.get(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")
        return copy.deepcopy(job)

    def status(self, job_id: str) -> str:
        job = self._store.get(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")
        return job.status

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return False
            if job.status == "queued":
                self._queue.remove(job_id)
                job.status = "cancelled"
                job.finished_at = self._clock()
                self._store.cancel_job(job)
                cancelled = True
            elif job.status == "running":
                job.cancel_requested = True
                cancelled = True
            else:
                cancelled = False
        self._wake_dispatch()
        return cancelled

    def change_priority(self, job_id: str, new_priority: int) -> bool:
        if not isinstance(new_priority, int):
            raise InvalidJobError("new_priority must be an integer")
        with self._lock:
            job = self._store.get(job_id)
            if job is None or job.status != "queued":
                return False
            changed = self._queue.change_priority(job_id, new_priority)
            if changed:
                job.priority = new_priority
            return changed

    def stats(self) -> dict:
        counts = {"queued": 0, "running": 0, "cancelled": 0}
        jobs = self._store.all_jobs()
        for job in jobs.values():
            counts[job.status] = counts.get(job.status, 0) + 1
        data = self._metrics.snapshot()
        data["queued"] = counts.get("queued", 0)
        data["running"] = counts.get("running", 0)
        data["cancelled"] = counts.get("cancelled", 0)
        data["total"] = len(jobs)
        return data

    def recover(self, func_provider: Optional[Callable[[Job], Callable]] = None) -> list:
        recovered = self._recovery.recover()
        if func_provider is not None:
            for job_id in recovered:
                job = self._store.get(job_id)
                if job is not None:
                    job.func = func_provider(job)
        self._wake_dispatch()
        return recovered

    def replay(self) -> int:
        """Number of WAL records currently in the log."""
        return self._store.record_count()

    def snapshot(self) -> int:
        """Write a checkpoint and truncate the WAL; returns covered offset."""
        return self._recovery.snapshot()

    def shutdown(self, wait: bool = True) -> None:
        with self._dispatch_cond:
            self._shutdown = True
            self._dispatch_cond.notify_all()
        if self._dispatch_thread is not None:
            self._dispatch_thread.join(timeout=10 if wait else 0.1)
        self._executor.shutdown(wait=wait)
        self._store.close()

    # ------------------------------------------------------------- internals

    def _wake_dispatch(self) -> None:
        with self._dispatch_cond:
            self._dispatch_cond.notify_all()

    def _dispatchable(self) -> bool:
        if self._executor.is_shutdown():
            return False
        item = self._queue.peek()
        if item is None:
            return False
        _, job_id = item
        job = self._store.get(job_id)
        return job is not None and job.func is not None and job.status == "queued"

    def _dispatch_loop(self) -> None:
        while True:
            with self._dispatch_cond:
                while not self._shutdown and not self._dispatchable():
                    self._dispatch_cond.wait(timeout=0.05)
                if self._shutdown and not self._dispatchable():
                    return
            self._dispatch_one()

    def _dispatch_one(self) -> None:
        item = self._queue.pop()
        if item is None:
            return
        _, job_id = item
        job = self._store.get(job_id)
        if job is None or job.status != "queued":
            return
        while not self._executor.is_shutdown():
            try:
                self._executor.submit(job)
                return
            except ExecutorFullError:
                self._executor.wait_available()
        # executor shut down while we held the job: put it back so it is not lost
        self._queue.put(job.priority, job_id, enqueued_at=job.enqueued_at)

    def _on_complete(self, job: Job) -> None:
        self._store.complete_job(job)
        if job.status == "succeeded":
            self._metrics.inc("succeeded")
        elif job.status == "failed":
            self._metrics.inc("failed")
        self._metrics.inc("deadline_hit", job.timeout_hits)
        self._metrics.inc("retried", job.retry_count)
