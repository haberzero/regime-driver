import json
import threading
import time
import uuid
from typing import Any, Callable, Optional

import recovery
from errors import (
    DuplicateJobError,
    ExecutorFullError,
    InvalidJobError,
    JobTimeoutError,
)
from executor import Executor
from idempotency import IdempotencyRegistry
from job_store import Job, JobStatus, JobStore
from metrics import Metrics
from priority_queue import PriorityQueue


class Scheduler:
    """Facade composing store, priority queue, executor, idempotency and metrics."""

    def __init__(
        self,
        wal_path: str,
        worker_count: int = 4,
        aging_interval: float = 5.0,
        aging_step: int = 1,
        max_queued: Optional[int] = None,
        backoff_base: float = 0.05,
        backoff_max: float = 1.0,
        jitter: float = 0.5,
        max_retries: int = 2,
        sleep_fn=None,
        now_fn=None,
        fsync: bool = False,
    ):
        if worker_count < 1:
            raise ValueError("worker_count must be >= 1")
        if max_queued is not None and max_queued < 1:
            raise ValueError("max_queued must be >= 1")
        if not isinstance(aging_interval, (int, float)) or aging_interval <= 0:
            raise ValueError("aging_interval must be > 0")
        if not isinstance(aging_step, int) or aging_step < 1:
            raise ValueError("aging_step must be an int >= 1")
        self._now_fn = now_fn or time.time
        self._sleep_fn = sleep_fn or time.sleep
        self._max_retries = max_retries
        self._wal_path = wal_path
        self._store = JobStore(wal_path, fsync=fsync, now_fn=self._now_fn)
        self._queue = PriorityQueue(
            aging_interval=aging_interval, aging_step=aging_step, now_fn=self._now_fn
        )
        self._registry = IdempotencyRegistry()
        self._metrics = Metrics()
        self._tasks_lock = threading.Lock()
        self._tasks: dict = {}
        self._submit_lock = threading.Lock()
        self._max_queued = max_queued if max_queued is not None else worker_count * 2
        self._executor = Executor(
            self._store,
            self._queue,
            self._metrics,
            self._tasks,
            worker_count=worker_count,
            sleep_fn=self._sleep_fn,
            now_fn=self._now_fn,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
            jitter=jitter,
        )
        self._executor.start()

    def register_task(self, name: str, fn: Callable) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("task name must be a non-empty string")
        if not callable(fn):
            raise ValueError("fn must be callable")
        with self._tasks_lock:
            existing = self._tasks.get(name)
            if existing is not None and existing is not fn:
                raise InvalidJobError(
                    f"task {name!r} already registered with a different function"
                )
            self._tasks[name] = fn

    def submit(
        self,
        task,
        *args,
        priority: int = 0,
        timeout: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        max_retries: Optional[int] = None,
        **kwargs,
    ) -> str:
        self._validate_params(priority, timeout, idempotency_key)
        retries = self._max_retries if max_retries is None else max_retries
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
            raise InvalidJobError("max_retries must be a non-negative int")
        name = self._resolve_task(task)
        try:
            json.dumps({"args": list(args), "kwargs": dict(kwargs)})
        except (TypeError, ValueError):
            raise InvalidJobError("args/kwargs must be JSON-serializable")
        if idempotency_key is not None and self._registry.contains(idempotency_key):
            raise DuplicateJobError(f"idempotency key {idempotency_key!r} already in use")
        with self._submit_lock:
            if self._store.pending_count() >= self._max_queued:
                raise ExecutorFullError(f"executor capacity {self._max_queued} reached")
            job_id = uuid.uuid4().hex
            if idempotency_key is not None and not self._registry.register(idempotency_key, job_id):
                raise DuplicateJobError(f"idempotency key {idempotency_key!r} already in use")
            job = Job(
                job_id=job_id,
                task=name,
                args=tuple(args),
                kwargs=dict(kwargs),
                priority=priority,
                timeout=timeout,
                max_retries=retries,
                idempotency_key=idempotency_key,
                submit_ts=self._now_fn(),
            )
            self._store.submit(job)
            self._queue.push(job_id, priority)
            self._metrics.inc("submitted")
        return job_id

    def get(self, job_id: str, timeout: Optional[float] = None) -> Any:
        job = self._store.wait_terminal(job_id, timeout=timeout)
        if not job.is_terminal:
            raise TimeoutError(f"timed out waiting for job {job_id!r}")
        if job.state == "COMPLETED":
            return job.result
        if job.timed_out:
            raise JobTimeoutError(job.error or "job timed out")
        if job.state == "CANCELLED":
            raise RuntimeError(f"job {job_id!r} was cancelled")
        raise RuntimeError(job.error or "job failed")

    def status(self, job_id: str) -> JobStatus:
        job = self._store.get(job_id)
        return JobStatus(
            job_id=job.job_id,
            task=job.task,
            state=job.state,
            priority=job.priority,
            attempt=job.attempt,
            max_retries=job.max_retries,
            timeout=job.timeout,
            idempotency_key=job.idempotency_key,
            submit_ts=job.submit_ts,
            started_ts=job.started_ts,
            completed_ts=job.completed_ts,
            error=job.error,
            result=job.result,
        )

    def cancel(self, job_id: str) -> bool:
        job = self._store.get(job_id)
        self._queue.remove(job_id)
        return self._store.cancel(job)

    def change_priority(self, job_id: str, new_priority: int) -> bool:
        if not isinstance(new_priority, int) or isinstance(new_priority, bool):
            raise InvalidJobError("new_priority must be an int")
        self._store.get(job_id)
        return self._queue.change_priority(job_id, new_priority)

    def stats(self) -> dict:
        result = self._metrics.snapshot()
        result["queued"] = self._queue.qsize()
        result["running"] = self._executor.in_flight()
        return result

    def replay(self) -> int:
        return self._store.line_count()

    def recover(self) -> dict:
        self._queue.clear()
        result = recovery.Recovery.recover(
            self._store, self._queue, self._registry, self._metrics, self._now_fn
        )
        jobs = result["jobs"]
        return {
            "jobs": len(jobs),
            "recovered": len(result["recovered_ids"]),
            "requeued": sum(1 for j in jobs if j.state == "QUEUED"),
        }

    def snapshot(self, path: Optional[str] = None) -> dict:
        path = path or (self._wal_path + ".snapshot.json")
        lines = self._store.line_count()
        jobs = []
        for job in self._store.all_jobs():
            jobs.append(
                {
                    "job_id": job.job_id,
                    "task": job.task,
                    "state": job.state,
                    "priority": job.priority,
                    "attempt": job.attempt,
                    "max_retries": job.max_retries,
                    "idempotency_key": job.idempotency_key,
                    "timeout": job.timeout,
                    "submit_ts": job.submit_ts,
                    "started_ts": job.started_ts,
                    "completed_ts": job.completed_ts,
                    "error": job.error,
                    "result": job.result,
                }
            )
        data = {"generated_at": self._now_fn(), "lines": lines, "jobs": jobs}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return {"path": path, "jobs": len(jobs), "lines": lines}

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
        self._store.close()

    def _resolve_task(self, task) -> str:
        if callable(task):
            name = getattr(task, "__name__", None) or "anonymous"
            with self._tasks_lock:
                existing = self._tasks.get(name)
                if existing is None:
                    self._tasks[name] = task
                elif existing is not task:
                    raise InvalidJobError(
                        f"task {name!r} already registered with a different function"
                    )
            return name
        if isinstance(task, str):
            with self._tasks_lock:
                if task not in self._tasks:
                    raise InvalidJobError(f"task {task!r} not registered")
            return task
        raise InvalidJobError("task must be a callable or a registered task name")

    @staticmethod
    def _validate_params(priority, timeout, idempotency_key) -> None:
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise InvalidJobError("priority must be an int")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
                raise InvalidJobError("timeout must be a positive number or None")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key:
                raise InvalidJobError("idempotency_key must be a non-empty string")
