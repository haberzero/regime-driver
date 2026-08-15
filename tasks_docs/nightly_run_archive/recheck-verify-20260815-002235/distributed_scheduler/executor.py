import random
import threading
import time
from collections import deque

from clock import Clock
from errors import ExecutorFullError, JobTimeoutError
from job_store import Job


class Executor:
    """Fixed-size worker pool.

    Each attempt runs in its own sub-thread and is joined with the job's
    timeout; a timed-out attempt raises JobTimeoutError and the worker thread
    is immediately reclaimed to pick up the next job (the abandoned sub-thread
    is detached; its result is discarded). Failures are retried with
    exponential backoff + half-jitter; `sleep_fn` and `rng` are injectable for
    deterministic tests. When retries are exhausted the job is marked failed
    and `on_complete(job)` is invoked.

    Capacity is workers + queue_size. Direct submit() while at capacity raises
    ExecutorFullError immediately (non-blocking); wait_available() provides
    backpressure for callers that prefer blocking.
    """

    def __init__(
        self,
        workers: int,
        queue_size: int = 1024,
        base_backoff: float = 0.1,
        cap_backoff: float = 30.0,
        max_attempts: int = 3,
        sleep_fn=time.sleep,
        rng=None,
        on_complete=None,
        clock: Clock = None,
    ):
        if not isinstance(workers, int) or workers <= 0:
            raise ValueError(f"workers must be a positive int, got {workers!r}")
        if not isinstance(queue_size, int) or queue_size < 0:
            raise ValueError(f"queue_size must be a non-negative int, got {queue_size!r}")
        self._workers = workers
        self._queue_size = queue_size
        self._base_backoff = base_backoff
        self._cap_backoff = cap_backoff
        self._max_attempts = max_attempts
        self._sleep = sleep_fn
        self._rng = rng if rng is not None else random.random
        self._on_complete = on_complete
        self._clock = clock if clock is not None else Clock()
        self._pending = deque()
        self._cond = threading.Condition()
        self._active = 0
        self._shutdown = False
        self._threads = []
        for _ in range(workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._threads.append(t)

    def submit(self, job: Job) -> None:
        with self._cond:
            if self._shutdown:
                raise RuntimeError("executor is shut down")
            if self._active >= self._workers and len(self._pending) >= self._queue_size:
                raise ExecutorFullError(
                    f"executor at capacity: workers={self._workers}, queue_size={self._queue_size}"
                )
            self._pending.append(job)
            self._cond.notify()

    def wait_available(self) -> None:
        """Block until a slot frees (or shutdown)."""
        with self._cond:
            while self._active >= self._workers and len(self._pending) >= self._queue_size:
                if self._shutdown:
                    return
                self._cond.wait()

    def is_shutdown(self) -> bool:
        with self._cond:
            return self._shutdown

    def run_sync(self, job: Job) -> Job:
        """Run a job to completion in the calling thread.

        Re-raises the terminal error (JobTimeoutError for timeouts) so tests
        can observe the exception path directly.
        """
        self._run_job(job)
        if job.status == "failed":
            if job.error_type == "JobTimeoutError":
                raise JobTimeoutError(job.error or "job timed out")
            raise RuntimeError(job.error or "job failed")
        return job

    def shutdown(self, wait: bool = True) -> None:
        with self._cond:
            self._shutdown = True
            self._cond.notify_all()
        if wait:
            for t in self._threads:
                t.join()

    def _worker_loop(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._shutdown:
                    self._cond.wait()
                if not self._pending:
                    return
                job = self._pending.popleft()
                self._active += 1
            try:
                self._run_job(job)
            finally:
                with self._cond:
                    self._active -= 1
                    self._cond.notify_all()

    def _run_job(self, job: Job) -> None:
        if job.status == "cancelled" or job.cancel_requested:
            job.status = "cancelled"
            job.finished_at = self._clock()
            self._complete(job)
            return
        while job.attempts < job.max_attempts:
            if job.cancel_requested:
                break
            job.status = "running"
            job.started_at = self._clock()
            try:
                result = self._run_once(job)
            except JobTimeoutError as e:
                job.timeout_hits += 1
                job.attempts += 1
                job.error = str(e)
                job.error_type = "JobTimeoutError"
                self._maybe_sleep(job)
                continue
            except Exception as e:
                job.attempts += 1
                job.error = f"{type(e).__name__}: {e}"
                job.error_type = type(e).__name__
                self._maybe_sleep(job)
                continue
            job.attempts += 1
            job.status = "succeeded"
            job.result = result
            job.finished_at = self._clock()
            self._complete(job)
            return
        if job.cancel_requested:
            job.status = "cancelled"
        else:
            job.status = "failed"
        job.finished_at = self._clock()
        self._complete(job)

    def _run_once(self, job: Job):
        fn = job.func
        if fn is None:
            raise RuntimeError(f"job {job.job_id!r} has no bound function")
        result_box = {}
        error_box = {}

        def target():
            try:
                result_box["result"] = fn(job)
            except Exception as e:
                error_box["error"] = e

        t = threading.Thread(target=target, daemon=True, name=f"attempt-{job.job_id}")
        t.start()
        t.join(timeout=job.timeout)
        if t.is_alive():
            raise JobTimeoutError(
                f"job {job.job_id!r} exceeded timeout {job.timeout}s"
            )
        if "error" in error_box:
            raise error_box["error"]
        return result_box["result"]

    def _maybe_sleep(self, job: Job) -> None:
        if job.attempts < job.max_attempts and not job.cancel_requested:
            job.retry_count += 1
            backoff = min(self._cap_backoff, self._base_backoff * (2 ** (job.attempts - 1)))
            self._sleep(backoff * (0.5 + 0.5 * self._rng()))

    def _complete(self, job: Job) -> None:
        if self._on_complete is not None:
            self._on_complete(job)
