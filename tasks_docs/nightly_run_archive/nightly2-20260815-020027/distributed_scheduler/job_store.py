import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from errors import JobNotFoundError, RecoveryError

_TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED")


@dataclass
class Job:
    job_id: str
    task: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    priority: int = 0
    timeout: Optional[float] = None
    max_retries: int = 0
    idempotency_key: Optional[str] = None
    submit_ts: float = 0.0
    state: str = "QUEUED"
    attempt: int = 0
    result: Any = None
    error: Optional[str] = None
    timed_out: bool = False
    started_ts: Optional[float] = None
    completed_ts: Optional[float] = None

    @property
    def deadline(self) -> Optional[float]:
        if self.timeout is None:
            return None
        return self.submit_ts + self.timeout

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES


@dataclass
class JobStatus:
    job_id: str
    task: str
    state: str
    priority: int
    attempt: int
    max_retries: int
    timeout: Optional[float]
    idempotency_key: Optional[str]
    submit_ts: float
    started_ts: Optional[float]
    completed_ts: Optional[float]
    error: Optional[str]
    result: Any


class JobStore:
    """Append-only WAL + in-memory index of all jobs.

    Every state transition appends one JSON line to the WAL. Appends are
    performed as a single buffered write under a lock, so a crashed process
    leaves at most one partial trailing line, which replay tolerates.
    """

    def __init__(self, path: str, fsync: bool = False, now_fn=time.time):
        self._path = path
        self._fsync = fsync
        self._now_fn = now_fn
        self._cond = threading.Condition()
        self._jobs: Dict[str, Job] = {}
        self._file = open(path, "ab")

    def _append(self, event: dict) -> None:
        line = json.dumps(event, sort_keys=True) + "\n"
        with self._cond:
            self._file.write(line.encode("utf-8"))
            self._file.flush()
            if self._fsync:
                import os

                os.fsync(self._file.fileno())

    def submit(self, job: Job) -> None:
        event = {
            "type": "submitted",
            "job_id": job.job_id,
            "task": job.task,
            "args": list(job.args),
            "kwargs": job.kwargs,
            "priority": job.priority,
            "timeout": job.timeout,
            "max_retries": job.max_retries,
            "idempotency_key": job.idempotency_key,
            "submit_ts": job.submit_ts,
        }
        with self._cond:
            self._append(event)
            self._jobs[job.job_id] = job
            self._cond.notify_all()

    def mark_started(self, job: Job, attempt: int) -> bool:
        with self._cond:
            if job.state == "CANCELLED":
                return False
            job.state = "RUNNING"
            job.attempt = attempt
            job.started_ts = self._now_fn()
            ts = job.started_ts
            self._append({"type": "started", "job_id": job.job_id, "attempt": attempt, "ts": ts})
            self._cond.notify_all()
            return True

    def complete(self, job: Job, result: Any) -> bool:
        with self._cond:
            if job.state == "CANCELLED":
                return False
            ts = self._now_fn()
            self._append({"type": "completed", "job_id": job.job_id, "result": result, "ts": ts})
            job.state = "COMPLETED"
            job.result = result
            job.completed_ts = ts
            self._cond.notify_all()
            return True

    def fail(self, job: Job, error: str, timed_out: bool = False) -> bool:
        with self._cond:
            if job.state == "CANCELLED":
                return False
            ts = self._now_fn()
            self._append({"type": "failed", "job_id": job.job_id, "error": str(error), "ts": ts})
            job.state = "FAILED"
            job.error = str(error)
            job.timed_out = timed_out
            job.completed_ts = ts
            self._cond.notify_all()
            return True

    def cancel(self, job: Job) -> bool:
        with self._cond:
            if job.is_terminal:
                return False
            ts = self._now_fn()
            self._append({"type": "cancelled", "job_id": job.job_id, "ts": ts})
            job.state = "CANCELLED"
            job.completed_ts = ts
            self._cond.notify_all()
            return True

    def requeue(self, job: Job) -> None:
        with self._cond:
            job.state = "QUEUED"
            self._cond.notify_all()

    def get(self, job_id: str) -> Job:
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(f"job {job_id!r} not found")
            return job

    def all_jobs(self) -> List[Job]:
        with self._cond:
            return list(self._jobs.values())

    def wait_terminal(self, job_id: str, timeout: Optional[float] = None) -> Job:
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(f"job {job_id!r} not found")
            deadline = None if timeout is None else self._now_fn() + timeout
            while not job.is_terminal:
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - self._now_fn()
                    if remaining <= 0:
                        return job
                    self._cond.wait(remaining)
            return job

    def pending_count(self) -> int:
        with self._cond:
            return sum(1 for job in self._jobs.values() if job.state in ("QUEUED", "RUNNING"))

    def line_count(self) -> int:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except FileNotFoundError:
            return 0

    def replay(self) -> List[Job]:
        """Replay the WAL and rebuild the in-memory index. Returns jobs in submit order."""
        with open(self._path, "r", encoding="utf-8") as f:
            raw = f.readlines()
        index: Dict[str, Job] = {}
        order: List[Job] = []
        last = len(raw) - 1
        for i, line in enumerate(raw):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                if i == last:
                    break
                raise RecoveryError(f"corrupt WAL line {i + 1}: not valid JSON")
            if not isinstance(ev, dict) or "type" not in ev:
                if i == last:
                    break
                raise RecoveryError(f"corrupt WAL line {i + 1}: malformed event")
            self._apply_event(index, order, ev, i)
        with self._cond:
            self._jobs = index
            self._cond.notify_all()
        return order

    @staticmethod
    def _apply_event(index: Dict[str, Job], order: List[Job], ev: dict, lineno: int) -> None:
        kind = ev["type"]
        if kind == "submitted":
            job = Job(
                job_id=ev["job_id"],
                task=ev["task"],
                args=tuple(ev["args"]),
                kwargs=dict(ev["kwargs"]),
                priority=ev["priority"],
                timeout=ev.get("timeout"),
                max_retries=ev.get("max_retries", 0),
                idempotency_key=ev.get("idempotency_key"),
                submit_ts=ev["submit_ts"],
            )
            index[job.job_id] = job
            order.append(job)
            return
        job = index.get(ev["job_id"])
        if job is None:
            raise RecoveryError(f"corrupt WAL line {lineno + 1}: event for unknown job")
        if kind == "started":
            job.state = "RUNNING"
            job.attempt = ev["attempt"]
            job.started_ts = ev["ts"]
        elif kind == "completed":
            job.state = "COMPLETED"
            job.result = ev.get("result")
            job.completed_ts = ev["ts"]
        elif kind == "failed":
            job.state = "FAILED"
            job.error = ev["error"]
            job.completed_ts = ev["ts"]
        elif kind == "cancelled":
            job.state = "CANCELLED"
            job.completed_ts = ev["ts"]
        else:
            raise RecoveryError(f"corrupt WAL line {lineno + 1}: unknown event type {kind!r}")

    def close(self) -> None:
        with self._cond:
            if not self._file.closed:
                self._file.flush()
                self._file.close()
