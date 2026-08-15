import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from errors import JobNotFoundError, RecoveryError

_TERMINAL_STATES = ("completed", "failed", "cancelled")


def _json_default(obj):
    if isinstance(obj, (tuple, set, frozenset)):
        return list(obj)
    if isinstance(obj, Exception):
        return f"{type(obj).__name__}: {obj}"
    return str(obj)


@dataclass
class JobRecord:
    job_id: str
    task: str
    state: str = "queued"
    priority: int = 0
    idempotency_key: Optional[str] = None
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    timeout: Optional[float] = None
    max_retries: int = 0
    attempts: int = 0
    result: Any = None
    error: Any = None
    created_at: float = 0.0


def _record_to_dict(record):
    return {
        "job_id": record.job_id,
        "task": record.task,
        "state": record.state,
        "priority": record.priority,
        "idempotency_key": record.idempotency_key,
        "args": record.args,
        "kwargs": record.kwargs,
        "timeout": record.timeout,
        "max_retries": record.max_retries,
        "attempts": record.attempts,
        "result": record.result,
        "error": record.error,
        "created_at": record.created_at,
    }


class JobStore:
    """Durable job persistence: WAL plus in-memory index.

    Every state transition (submit / run / complete / fail / cancel /
    priority change) is appended to the append-only WAL as one JSON line.
    Each append is a single ``write`` + ``flush`` + ``fsync`` under a lock,
    making it atomic and durable. The in-memory index is a derived cache
    rebuilt from snapshot + WAL during recovery.
    """

    def __init__(self, dir_path):
        self.dir = os.path.abspath(dir_path)
        os.makedirs(self.dir, exist_ok=True)
        self.wal_path = os.path.join(self.dir, "wal.log")
        self.snapshot_path = os.path.join(self.dir, "snapshot.json")
        self._wal_lock = threading.RLock()
        self._idx_lock = threading.RLock()
        self._jobs = {}
        self._by_key = {}
        self._seq = 0
        self._wal_fh = open(self.wal_path, "a+")

    def close(self):
        with self._wal_lock:
            self._wal_fh.flush()
            os.fsync(self._wal_fh.fileno())
            self._wal_fh.close()

    def _append(self, record):
        record["seq"] = self._seq
        self._seq += 1
        self._wal_fh.write(json.dumps(record, default=_json_default) + "\n")
        self._wal_fh.flush()
        os.fsync(self._wal_fh.fileno())

    def add(self, job, precheck=None):
        with self._wal_lock, self._idx_lock:
            if precheck is not None:
                precheck(job)
            self._jobs[job.job_id] = job
            if job.idempotency_key is not None:
                self._by_key[job.idempotency_key] = job.job_id
            self._append({
                "type": "SUBMIT",
                "job_id": job.job_id,
                "task": job.task,
                "priority": job.priority,
                "idempotency_key": job.idempotency_key,
                "args": job.args,
                "kwargs": job.kwargs,
                "timeout": job.timeout,
                "max_retries": job.max_retries,
                "created_at": job.created_at,
            })

    def mark_running(self, job_id, attempt):
        with self._wal_lock, self._idx_lock:
            job = self._jobs[job_id]
            job.state = "running"
            job.attempts = max(job.attempts, attempt)
            self._append({"type": "RUNNING", "job_id": job_id, "attempt": attempt})

    def mark_completed(self, job_id, result):
        with self._wal_lock, self._idx_lock:
            job = self._jobs[job_id]
            if job.state == "cancelled":
                return False
            job.state = "completed"
            job.result = result
            self._append({"type": "COMPLETED", "job_id": job_id, "result": result})
            return True

    def mark_failed(self, job_id, error):
        with self._wal_lock, self._idx_lock:
            job = self._jobs[job_id]
            if job.state == "cancelled":
                return False
            job.state = "failed"
            job.error = error
            self._append({"type": "FAILED", "job_id": job_id, "error": error})
            return True

    def mark_cancelled(self, job_id):
        with self._wal_lock, self._idx_lock:
            job = self._jobs[job_id]
            if job.state in _TERMINAL_STATES:
                return False
            job.state = "cancelled"
            self._append({"type": "CANCELLED", "job_id": job_id})
            return True

    def mark_queued(self, job_id):
        with self._idx_lock:
            self._jobs[job_id].state = "queued"

    def set_priority(self, job_id, priority):
        with self._wal_lock, self._idx_lock:
            job = self._jobs[job_id]
            if job.state in _TERMINAL_STATES:
                return False
            job.priority = priority
            self._append({"type": "PRIORITY", "job_id": job_id, "priority": priority})
            return True

    def get(self, job_id):
        with self._idx_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return job

    def get_by_key(self, key):
        with self._idx_lock:
            job_id = self._by_key.get(key)
            if job_id is None:
                return None
            return self._jobs.get(job_id)

    def idempotency_keys(self):
        with self._idx_lock:
            return set(self._by_key)

    def all_jobs(self):
        with self._idx_lock:
            return dict(self._jobs)

    def is_empty(self):
        with self._idx_lock:
            return not self._jobs

    def replay(self):
        """Number of records currently present in the WAL."""
        with self._wal_lock:
            count = 0
            with open(self.wal_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RecoveryError(f"corrupt WAL record: {exc}") from exc
                    count += 1
            return count

    def recover(self):
        """Rebuild all in-memory state from snapshot + WAL.

        Returns the ids of jobs that were executing (state ``running``) when
        the log ended; the caller rolls those back to queued for rescheduling.
        """
        with self._wal_lock, self._idx_lock:
            self._jobs.clear()
            self._by_key.clear()
            self._seq = 0
            watermark = None
            if os.path.exists(self.snapshot_path):
                with open(self.snapshot_path) as fh:
                    snapshot = json.load(fh)
                watermark = snapshot["watermark_seq"]
                self._seq = snapshot["next_seq"]
                for payload in snapshot["jobs"]:
                    record = self._record_from_dict(payload)
                    self._jobs[record.job_id] = record
                    if record.idempotency_key is not None:
                        self._by_key[record.idempotency_key] = record.job_id
            with open(self.wal_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RecoveryError(f"corrupt WAL record: {exc}") from exc
                    if watermark is not None and event["seq"] <= watermark:
                        continue
                    self._apply(event)
                    self._seq = max(self._seq, event["seq"] + 1)
            return [job.job_id for job in self._jobs.values() if job.state == "running"]

    def snapshot(self):
        """Write a checkpoint of the full index and truncate the WAL tail.

        Both the snapshot write and the WAL truncation happen under the WAL
        and index locks, and the snapshot records the watermark (last applied
        seq) so no record written after it can ever be lost.
        """
        with self._wal_lock, self._idx_lock:
            watermark = self._seq - 1
            payload = {
                "watermark_seq": watermark,
                "next_seq": self._seq,
                "jobs": [_record_to_dict(record) for record in self._jobs.values()],
            }
            tmp = self.snapshot_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh, default=_json_default)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.snapshot_path)
            self._truncate_wal(watermark)

    def _truncate_wal(self, watermark):
        tail = []
        with open(self.wal_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if event["seq"] > watermark:
                    tail.append(event)
        tmp = self.wal_path + ".tmp"
        with open(tmp, "w") as fh:
            for event in tail:
                fh.write(json.dumps(event, default=_json_default) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.wal_path)
        self._wal_fh.close()
        self._wal_fh = open(self.wal_path, "a+")

    def _apply(self, event):
        event_type = event["type"]
        job_id = event["job_id"]
        if event_type == "SUBMIT":
            record = JobRecord(
                job_id=job_id,
                task=event["task"],
                priority=event["priority"],
                idempotency_key=event.get("idempotency_key"),
                args=list(event.get("args") or []),
                kwargs=dict(event.get("kwargs") or {}),
                timeout=event.get("timeout"),
                max_retries=event.get("max_retries", 0),
                created_at=event.get("created_at", 0.0),
            )
            self._jobs[job_id] = record
            if record.idempotency_key is not None:
                self._by_key[record.idempotency_key] = job_id
        elif event_type == "RUNNING":
            record = self._jobs[job_id]
            record.state = "running"
            record.attempts = max(record.attempts, event.get("attempt", 1))
        elif event_type == "COMPLETED":
            record = self._jobs[job_id]
            record.state = "completed"
            record.result = event.get("result")
        elif event_type == "FAILED":
            record = self._jobs[job_id]
            record.state = "failed"
            record.error = event.get("error")
        elif event_type == "CANCELLED":
            record = self._jobs[job_id]
            record.state = "cancelled"
        elif event_type == "PRIORITY":
            record = self._jobs[job_id]
            record.priority = event["priority"]
        else:
            raise RecoveryError(f"unknown WAL event type: {event_type!r}")

    def _record_from_dict(self, payload):
        return JobRecord(
            job_id=payload["job_id"],
            task=payload["task"],
            state=payload.get("state", "queued"),
            priority=payload.get("priority", 0),
            idempotency_key=payload.get("idempotency_key"),
            args=list(payload.get("args") or []),
            kwargs=dict(payload.get("kwargs") or {}),
            timeout=payload.get("timeout"),
            max_retries=payload.get("max_retries", 0),
            attempts=payload.get("attempts", 0),
            result=payload.get("result"),
            error=payload.get("error"),
            created_at=payload.get("created_at", 0.0),
        )
