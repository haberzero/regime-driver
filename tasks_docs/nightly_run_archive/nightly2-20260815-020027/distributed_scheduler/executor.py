import random
import threading
import time
from typing import Callable, Dict, Optional

from errors import JobTimeoutError


class Executor:
    """Fixed-size daemon worker pool.

    Each job runs in its own daemon thread so a per-attempt timeout can abandon
    a stuck task without blocking the pool. Failed attempts are retried with
    exponential backoff plus jitter (sleep function injectable for tests) until
    the job's retry budget is exhausted, after which the job is marked FAILED.
    """

    def __init__(
        self,
        store,
        queue,
        metrics,
        tasks: Dict[str, Callable],
        worker_count: int = 4,
        sleep_fn=time.sleep,
        now_fn=time.time,
        backoff_base: float = 0.1,
        backoff_max: float = 5.0,
        jitter: float = 0.5,
    ):
        if worker_count < 1:
            raise ValueError("worker_count must be >= 1")
        self._store = store
        self._queue = queue
        self._metrics = metrics
        self._tasks = tasks
        self._worker_count = worker_count
        self._sleep_fn = sleep_fn
        self._now_fn = now_fn
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._jitter = jitter
        self._running = set()
        self._running_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []

    def start(self) -> None:
        for i in range(self._worker_count):
            t = threading.Thread(target=self._loop, name=f"executor-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def in_flight(self) -> int:
        with self._running_lock:
            return len(self._running)

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        self._queue.close()
        self._queue.notify_all()
        if wait:
            for t in self._threads:
                t.join()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.pop(block=True)
            if job_id is None:
                return
            self._run_job(job_id)

    def _run_job(self, job_id: str) -> None:
        job = self._store.get(job_id)
        with self._running_lock:
            self._running.add(job_id)
        try:
            if not self._store.mark_started(job, job.attempt + 1):
                return
            deadline = job.deadline
            if deadline is not None and self._now_fn() >= deadline:
                self._store.fail(job, "deadline exceeded before execution", timed_out=True)
                self._metrics.inc("deadline_hit")
                self._metrics.inc("failed")
                return
            task_fn = self._tasks.get(job.task)
            if task_fn is None:
                raise RuntimeError(f"task {job.task!r} not registered")
            result = self._execute(task_fn, job.args, job.kwargs, deadline)
            if self._store.complete(job, result):
                self._metrics.inc("succeeded")
        except JobTimeoutError as exc:
            if self._store.fail(job, str(exc), timed_out=True):
                self._metrics.inc("deadline_hit")
                self._metrics.inc("failed")
        except Exception as exc:
            if job.attempt <= job.max_retries:
                self._metrics.inc("retried")
                self._store.requeue(job)
                delay = self._backoff_delay(job.attempt)
                self._sleep_fn(delay)
                if not self._stop.is_set():
                    self._queue.push(job.job_id, job.priority)
            elif self._store.fail(job, str(exc)):
                self._metrics.inc("failed")
        finally:
            with self._running_lock:
                self._running.discard(job_id)

    def _execute(self, task_fn: Callable, args: tuple, kwargs: dict, deadline: Optional[float]):
        box = {}

        def _run() -> None:
            try:
                box["ok"] = True
                box["value"] = task_fn(*args, **kwargs)
            except Exception as exc:
                box["ok"] = False
                box["error"] = exc

        t = threading.Thread(target=_run, name="job-runner", daemon=True)
        t.start()
        if deadline is None:
            t.join()
        else:
            remaining = deadline - self._now_fn()
            if remaining <= 0:
                raise JobTimeoutError("deadline exceeded before execution")
            t.join(remaining)
            if t.is_alive():
                raise JobTimeoutError(f"job timed out after {remaining:.3f}s")
        if box.get("ok"):
            return box["value"]
        raise box["error"]

    def _backoff_delay(self, attempt: int) -> float:
        cap = min(self._backoff_max, self._backoff_base * (2 ** (attempt - 1)))
        return cap * random.uniform(1.0 - self._jitter, 1.0 + self._jitter)
