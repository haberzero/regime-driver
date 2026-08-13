"""Fixed-size worker pool with per-job timeout, exponential-backoff retries.

Each job runs in its own daemon thread so a blocking job function cannot
freeze the pool. The pool worker waits on the run's completion event up to
the job's timeout; on expiry it raises ``JobTimeoutError`` and the slot is
reclaimed (the runaway thread is detached). Backoff is exponential with
full jitter and is injected via ``sleep``/``rng`` for deterministic tests.
"""

import queue
import random
import threading
import time

from errors import ExecutorFullError, JobTimeoutError


class _NoopCallbacks:
    def on_start(self, job):
        return True

    def on_succeeded(self, job):
        pass

    def on_failed(self, job, exc):
        pass

    def on_timeout(self, job, exc):
        pass


class Executor:
    def __init__(self, num_workers, callbacks=None, sleep=time.sleep, clock=time.time,
                 base_backoff=0.05, max_backoff=1.0, rng=None, max_pending=None):
        if num_workers < 1:
            raise ValueError("num_workers must be >= 1")
        self._num = num_workers
        self._callbacks = callbacks or _NoopCallbacks()
        self._sleep = sleep
        self._clock = clock
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self._rng = rng if rng is not None else random.random
        self._max_pending = max_pending if max_pending is not None else num_workers
        self._queue = queue.Queue()
        self._cond = threading.Condition()
        self._workers = []

    def start(self):
        for _ in range(self._num):
            thread = threading.Thread(target=self._worker, daemon=True)
            thread.start()
            self._workers.append(thread)

    def _worker(self):
        while True:
            job = self._queue.get()
            if job is None:
                return
            with self._cond:
                self._cond.notify_all()
            if not self._callbacks.on_start(job):
                continue
            try:
                self.run_job(job)
            except JobTimeoutError as exc:
                self._callbacks.on_timeout(job, exc)
            except BaseException as exc:
                self._callbacks.on_failed(job, exc)
            else:
                self._callbacks.on_succeeded(job)

    def wait_for_capacity(self, stop=None):
        with self._cond:
            while self._queue.qsize() >= self._max_pending:
                if stop is not None and stop.is_set():
                    return
                self._cond.wait(0.05)

    def dispatch(self, job):
        with self._cond:
            if self._queue.qsize() >= self._max_pending:
                raise ExecutorFullError(
                    "executor pending queue is full (limit {})".format(self._max_pending))
            self._queue.put(job)
            self._cond.notify_all()

    def run_job(self, job):
        """Run ``job.fn`` once with an independent timeout. Raises on failure."""
        if job.fn is None:
            raise RuntimeError("job {!r} has no callable".format(job.job_id))
        deadline = self._clock() + job.timeout
        done = threading.Event()
        box = {}

        def inner():
            try:
                result = job.fn()
                box["ok"] = True
                box["result"] = result
                job.result = result
            except BaseException as exc:
                box["ok"] = False
                box["exc"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=inner, daemon=True)
        thread.start()
        remaining = deadline - self._clock()
        if remaining > 0:
            done.wait(remaining)
        if done.is_set():
            if box.get("ok", False):
                return box["result"]
            raise box["exc"]
        raise JobTimeoutError(
            "job {!r} exceeded timeout of {}s".format(job.job_id, job.timeout))

    def backoff_for(self, attempt):
        delay = min(self._max_backoff, self._base_backoff * (2 ** (attempt - 1)))
        delay *= self._rng()
        return delay

    def stop(self):
        for _ in range(self._num):
            self._queue.put(None)
