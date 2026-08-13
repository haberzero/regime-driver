"""Job persistence: append-only WAL log + in-memory index + replay recovery.

The WAL is a JSON-lines file. Every mutation (submit / start / retry /
succeed / fail / timeout / cancel / recover / priority) is appended as a
single atomic record (one ``os.write`` on an O_APPEND fd followed by
``fsync``). A torn write can only produce a partial trailing line, which
replay tolerates by stopping at it; any malformed line in the middle of the
log is treated as corruption and raises ``RecoveryError``.
"""

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from errors import RecoveryError

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELED = "canceled"

TERMINAL = (SUCCEEDED, FAILED, CANCELED)

_VALID_STATES = (QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELED)


@dataclass
class Job:
    job_id: str
    priority: int
    timeout: float
    max_retries: int
    created_at: float
    fn: Optional[Callable] = None
    idempotency_key: Optional[str] = None
    state: str = QUEUED
    attempts: int = 0
    error: Optional[str] = None
    result: Any = None
    finished_at: Optional[float] = None

    def to_dict(self):
        return {
            "id": self.job_id,
            "priority": self.priority,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "state": self.state,
            "attempts": self.attempts,
            "error": self.error,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            job_id=data["id"],
            priority=data["priority"],
            timeout=data["timeout"],
            max_retries=data["max_retries"],
            idempotency_key=data.get("idempotency_key"),
            created_at=data["created_at"],
            state=data.get("state", QUEUED),
            attempts=data.get("attempts", 0),
            error=data.get("error"),
            finished_at=data.get("finished_at"),
        )


class JobStore:
    def __init__(self, wal_path):
        self._path = Path(wal_path)
        self._snap_path = self._path.with_suffix(".snap")
        self._lock = threading.RLock()
        self._jobs = {}
        self._by_key = {}
        self._sn = 0

    # -- persistence -----------------------------------------------------

    def _append(self, record):
        record.setdefault("sn", self._sn)
        self._sn += 1
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(str(self._path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)

    def count_records(self):
        if not self._path.exists():
            return 0
        n = 0
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
        return n

    def replay(self):
        """Rebuild in-memory state from snapshot + WAL. Returns metrics counts."""
        counts = {k: 0 for k in ("submitted", "succeeded", "failed",
                                 "retried", "recovered", "deadline_hit")}
        jobs = {}
        by_key = {}
        snap_sn = None
        if self._snap_path.exists():
            with open(self._snap_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            snap_sn = data.get("snap_sn", -1)
            for jd in data.get("jobs", []):
                job = Job.from_dict(jd)
                jobs[job.job_id] = job
                if job.idempotency_key:
                    by_key[job.idempotency_key] = job.job_id
            counts.update(data.get("counts", {}))
            self._sn = max(self._sn, snap_sn + 1)
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            sn_max = snap_sn if snap_sn is not None else -1
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    if i == len(lines) - 1:
                        break  # torn trailing write from a crash
                    raise RecoveryError(
                        "corrupt WAL record at line {}".format(i + 1))
                if snap_sn is not None and record.get("sn", 0) <= snap_sn:
                    continue
                self._apply(record, jobs, by_key, counts)
                sn_max = max(sn_max, record.get("sn", 0))
            self._sn = max(self._sn, sn_max + 1)
        self._jobs = jobs
        self._by_key = by_key
        return counts

    def snapshot(self, counts=None):
        """Write a full-state checkpoint atomically, then truncate the WAL."""
        with self._lock:
            data = {
                "snap_sn": self._sn - 1,
                "jobs": [j.to_dict() for j in self._jobs.values()],
                "counts": counts or {},
            }
            tmp = self._snap_path.with_suffix(".snap.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._snap_path)
            with open(self._path, "w", encoding="utf-8"):
                pass

    # -- mutations (each updates memory and appends a WAL record) ---------

    def submit(self, job):
        with self._lock:
            self._jobs[job.job_id] = job
            if job.idempotency_key:
                self._by_key[job.idempotency_key] = job.job_id
            self._append({
                "type": "submit",
                "id": job.job_id,
                "priority": job.priority,
                "timeout": job.timeout,
                "max_retries": job.max_retries,
                "idempotency_key": job.idempotency_key,
                "created_at": job.created_at,
            })

    def mark_started(self, job_id, at=None):
        with self._lock:
            job = self._jobs[job_id]
            job.state = RUNNING
            job.attempts += 1
            job.error = None
            self._append({"type": "start", "id": job_id, "at": at})

    def mark_retry(self, job_id, at=None):
        with self._lock:
            self._jobs[job_id].state = QUEUED
            self._append({"type": "retry", "id": job_id, "at": at})

    def mark_succeeded(self, job_id, at=None):
        with self._lock:
            job = self._jobs[job_id]
            job.state = SUCCEEDED
            job.finished_at = at
            self._append({"type": "succeed", "id": job_id, "at": at})

    def mark_failed(self, job_id, error=None, at=None):
        with self._lock:
            job = self._jobs[job_id]
            job.state = FAILED
            job.error = error
            job.finished_at = at
            self._append({"type": "fail", "id": job_id, "error": error, "at": at})

    def mark_timeout(self, job_id, at=None):
        with self._lock:
            self._append({"type": "timeout", "id": job_id, "at": at})

    def mark_canceled(self, job_id, at=None):
        with self._lock:
            self._jobs[job_id].state = CANCELED
            self._append({"type": "cancel", "id": job_id, "at": at})

    def mark_recovered(self, job_id, at=None):
        with self._lock:
            self._jobs[job_id].state = QUEUED
            self._append({"type": "recover", "id": job_id, "at": at})

    def set_priority(self, job_id, priority, at=None):
        with self._lock:
            self._jobs[job_id].priority = priority
            self._append({"type": "priority", "id": job_id, "priority": priority, "at": at})

    # -- reads -------------------------------------------------------------

    def get(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def get_by_key(self, key):
        with self._lock:
            job_id = self._by_key.get(key)
            if job_id is None:
                return None
            return self._jobs.get(job_id)

    def all(self):
        with self._lock:
            return list(self._jobs.values())

    def __len__(self):
        with self._lock:
            return len(self._jobs)

    # -- replay application ------------------------------------------------

    @staticmethod
    def _apply(record, jobs, by_key, counts):
        record_type = record["type"]
        if record_type == "submit":
            job = Job(
                job_id=record["id"],
                priority=record["priority"],
                timeout=record["timeout"],
                max_retries=record["max_retries"],
                idempotency_key=record.get("idempotency_key"),
                created_at=record["created_at"],
            )
            jobs[job.job_id] = job
            if job.idempotency_key:
                by_key[job.idempotency_key] = job.job_id
            counts["submitted"] += 1
        elif record_type == "priority":
            jobs[record["id"]].priority = record["priority"]
        elif record_type == "start":
            job = jobs[record["id"]]
            job.state = RUNNING
            job.attempts += 1
        elif record_type == "retry":
            jobs[record["id"]].state = QUEUED
            counts["retried"] += 1
        elif record_type == "succeed":
            job = jobs[record["id"]]
            job.state = SUCCEEDED
            job.finished_at = record.get("at")
            counts["succeeded"] += 1
        elif record_type == "fail":
            job = jobs[record["id"]]
            job.state = FAILED
            job.error = record.get("error")
            job.finished_at = record.get("at")
            counts["failed"] += 1
        elif record_type == "timeout":
            counts["deadline_hit"] += 1
        elif record_type == "cancel":
            jobs[record["id"]].state = CANCELED
        elif record_type == "recover":
            jobs[record["id"]].state = QUEUED
            counts["recovered"] += 1
        else:
            raise RecoveryError("unknown WAL record type {!r}".format(record_type))
