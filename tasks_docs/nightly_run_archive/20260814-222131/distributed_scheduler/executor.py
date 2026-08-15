import queue
import random
import threading
import time

from errors import ExecutorFullError, InvalidJobError, JobNotFoundError, JobTimeoutError


class Executor:
    """Fixed-size worker pool with per-job timeout and retry-with-backoff.

    A job is handed to the executor once it leaves the priority queue; the
    executor owns the retry loop. Every attempt runs under its own timeout
    (a timed-out attempt raises JobTimeoutError, counts a deadline hit and,
    if budget remains, is retried with exponential backoff + full jitter).
    When the retry budget is exhausted the job is marked failed.
    """

    def __init__(self, pool_size, store, metrics, sleep_fn=time.sleep,
                 random_fn=random.uniform, base_backoff=0.5, max_backoff=60.0,
                 on_idle=None):
        if not isinstance(pool_size, int) or pool_size <= 0:
            raise ValueError("pool_size must be a positive int")
        self.pool_size = pool_size
        self._store = store
        self._metrics = metrics
        self._sleep = sleep_fn
        self._random = random_fn
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self._on_idle = on_idle or (lambda: None)
        self._cond = threading.Condition()
        self._free = pool_size
        self._queue = queue.Queue()
        self._workers = [
            threading.Thread(target=self._worker, daemon=True)
            for _ in range(pool_size)
        ]
        for worker in self._workers:
            worker.start()

    def free_slots(self):
        with self._cond:
            return self._free

    def submit(self, job, resolve):
        with self._cond:
            if self._free <= 0:
                raise ExecutorFullError(job.job_id, self.pool_size)
            self._free -= 1
        self._queue.put((job, resolve))

    def shutdown(self):
        for _ in range(self.pool_size):
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=1.0)

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            job, resolve = item
            try:
                self._execute(job, resolve)
            except Exception:
                self._store.mark_failed(job.job_id, "internal executor error")
                self._metrics.inc("failed")
            finally:
                with self._cond:
                    self._free += 1
                self._on_idle()

    def _execute(self, job, resolve):
        try:
            current = self._store.get(job.job_id)
        except JobNotFoundError:
            return
        if current.state == "cancelled":
            return
        try:
            fn = resolve(job)
        except KeyError:
            self._store.mark_failed(
                job.job_id, InvalidJobError(f"unknown task: {job.task!r}")
            )
            self._metrics.inc("failed")
            return
        attempt = current.attempts
        retries_used = max(0, attempt - 1)
        while True:
            attempt += 1
            if self._store.get(job.job_id).state == "cancelled":
                return
            self._store.mark_running(job.job_id, attempt)
            timed_out = False
            error = None
            try:
                result = self._run_with_timeout(fn, job)
                if self._store.get(job.job_id).state == "cancelled":
                    return
                self._store.mark_completed(job.job_id, result)
                self._metrics.inc("succeeded")
                return
            except JobTimeoutError as exc:
                error, timed_out = exc, True
            except Exception as exc:
                error = exc
            if timed_out:
                self._metrics.inc("deadline_hit")
            if retries_used < current.max_retries:
                retries_used += 1
                self._metrics.inc("retried")
                self._sleep(self._backoff(retries_used))
                continue
            self._store.mark_failed(job.job_id, error)
            self._metrics.inc("failed")
            return

    def _backoff(self, retry_number):
        cap = min(self._base_backoff * (2 ** (retry_number - 1)), self._max_backoff)
        if cap <= 0:
            return 0.0
        return self._random(0.0, cap)

    def _run_with_timeout(self, fn, job):
        if job.timeout is None:
            return fn(*job.args, **job.kwargs)
        box = {}

        def target():
            try:
                box["value"] = fn(*job.args, **job.kwargs)
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(job.timeout)
        if thread.is_alive():
            raise JobTimeoutError(job.job_id, job.timeout)
        if "error" in box:
            raise box["error"]
        return box.get("value")
