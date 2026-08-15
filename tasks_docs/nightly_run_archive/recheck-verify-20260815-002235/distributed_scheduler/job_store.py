import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Optional

from errors import RecoveryError


@dataclass
class Job:
    """A unit of work. `func` is in-memory only (never persisted to the WAL)."""

    job_id: str
    priority: int = 0
    payload: Any = None
    idempotency_key: Optional[str] = None
    status: str = "queued"
    timeout: Optional[float] = None
    max_attempts: int = 3
    attempts: int = 0
    created_at: float = 0.0
    enqueued_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    timeout_hits: int = 0
    retry_count: int = 0
    cancel_requested: bool = False
    func: Any = None


def job_to_dict(job: Job) -> dict:
    """Durable projection of a Job (excludes `func` and transient fields)."""
    return {
        "job_id": job.job_id,
        "priority": job.priority,
        "payload": job.payload,
        "idempotency_key": job.idempotency_key,
        "timeout": job.timeout,
        "max_attempts": job.max_attempts,
        "status": job.status,
        "attempts": job.attempts,
        "created_at": job.created_at,
        "enqueued_at": job.enqueued_at,
    }


def encode_value(value: Any) -> Any:
    """Return `value` unchanged if JSON-serializable, else a repr marker."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return {"__repr__": repr(value)}


class JobStore:
    """WAL append-only log + in-memory job index.

    Appends are atomic (single write() to an O_APPEND fd under a lock) and
    fsync'd before returning to the caller. Records are newline-delimited JSON;
    a crash mid-append can leave a partial trailing line, which load() skips.
    """

    def __init__(self, path: str, fsync: bool = True):
        self.path = path
        self._fsync = fsync
        self.lock = threading.RLock()
        self._fh = open(path, "ab")
        self._fh.flush()
        self._offset = os.path.getsize(path)
        self._max_seq = 0
        self._index = {}
        self._closed = False

    def _append(self, record: dict) -> int:
        # caller holds self.lock
        self._max_seq += 1
        full = {"v": 1, "seq": self._max_seq, **record}
        line = (json.dumps(full) + "\n").encode("utf-8")
        self._fh.write(line)
        self._fh.flush()
        if self._fsync:
            os.fsync(self._fh.fileno())
        self._offset += len(line)
        return self._max_seq

    def submit_job(self, job: Job) -> int:
        with self.lock:
            seq = self._append({"op": "submit", "job": job_to_dict(job)})
            self._index[job.job_id] = job
            return seq

    def complete_job(self, job: Job) -> int:
        with self.lock:
            seq = self._append(
                {
                    "op": "complete",
                    "job_id": job.job_id,
                    "status": job.status,
                    "result": encode_value(job.result),
                    "error": job.error,
                    "attempts": job.attempts,
                    "finished_at": job.finished_at,
                }
            )
            self._index[job.job_id] = job
            return seq

    def cancel_job(self, job: Job) -> int:
        with self.lock:
            seq = self._append(
                {"op": "cancel", "job_id": job.job_id, "finished_at": job.finished_at}
            )
            self._index[job.job_id] = job
            return seq

    def get(self, job_id: str) -> Optional[Job]:
        with self.lock:
            return self._index.get(job_id)

    def all_jobs(self) -> dict:
        with self.lock:
            return dict(self._index)

    def max_seq(self) -> int:
        with self.lock:
            return self._max_seq

    def durable_offset(self) -> int:
        """Byte offset of the end of the last fsync'd WAL record."""
        with self.lock:
            return self._offset

    def truncate(self) -> None:
        """Truncate the WAL to empty (only legal after the snapshot is durable)."""
        with self.lock:
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.flush()
            if self._fsync:
                os.fsync(self._fh.fileno())
            self._offset = 0

    def read_records(self):
        """Read all complete WAL records.

        Returns (records, clean_offset): `records` is a list of
        (start_offset, record) pairs; `clean_offset` is the byte offset just
        past the last complete record. A partial trailing line (crash
        mid-append) is skipped and reflected only in clean_offset; a corrupt
        non-tail line raises RecoveryError.
        """
        if not os.path.exists(self.path):
            return [], 0
        with open(self.path, "rb") as f:
            data = f.read()
        records = []
        offset = 0
        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines = lines[:-1]
        else:
            lines = lines[:-1]
        for raw in lines:
            if not raw.strip():
                offset += len(raw) + 1
                continue
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise RecoveryError(f"corrupt WAL record at offset {offset}: {raw!r}") from e
            records.append((offset, rec))
            offset += len(raw) + 1
        return records, offset

    def record_count(self) -> int:
        return len(self.read_records()[0])

    def truncate_to(self, offset: int) -> None:
        """Truncate the WAL to a clean record boundary (discard a torn tail)."""
        with self.lock:
            if offset < self._offset:
                self._fh.seek(offset)
                self._fh.truncate()
                self._fh.flush()
                if self._fsync:
                    os.fsync(self._fh.fileno())
                self._offset = offset

    def restore_index(self, jobs: dict, max_seq: int) -> None:
        with self.lock:
            self._index = dict(jobs)
            self._max_seq = max_seq
            self._offset = os.path.getsize(self.path)

    def close(self) -> None:
        with self.lock:
            if self._closed:
                return
            self._fh.close()
            self._closed = True
