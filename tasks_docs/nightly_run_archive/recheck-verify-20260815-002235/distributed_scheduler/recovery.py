import json
import os

from clock import Clock
from errors import RecoveryError
from idempotency import IdempotencyIndex
from job_store import Job, JobStore, job_to_dict
from metrics import Metrics
from priority_queue import PriorityQueue

_TERMINAL = ("succeeded", "failed", "cancelled")


class Recovery:
    """Crash recovery: checkpoint + incremental WAL replay.

    recover():
      1. Load the latest snapshot (if any); replay only WAL records whose seq
         is greater than the snapshot's max_seq (records covered by the
         snapshot are skipped exactly, never re-applied). Using the globally
         monotonic seq as the cutoff is robust across WAL truncation.
      2. Rebuild the store index, idempotency index and max seq.
      3. Re-queue every non-terminal job as queued so it is re-dispatched.
         Completed idempotent jobs stay completed and are never re-run.

    snapshot():
      Writes a full-state snapshot file, fsyncs it, then truncates the WAL.
      Safety invariant: the snapshot is built only from WAL state already
      fsync'd (offset <= durable_offset), and the truncation happens only
      after the snapshot file is durable. A crash between snapshot-fsync and
      WAL-truncate leaves the full WAL; recovery skips records covered by the
      snapshot by seq (records with seq <= snapshot.max_seq), so correctness
      never relies on idempotent replay.
    """

    def __init__(
        self,
        store: JobStore,
        queue: PriorityQueue,
        idem: IdempotencyIndex,
        metrics: Metrics,
        clock: Clock = None,
    ):
        self._store = store
        self._queue = queue
        self._idem = idem
        self._metrics = metrics
        self._clock = clock if clock is not None else Clock()

    def snapshot_path(self) -> str:
        return self._store.path + ".snapshot"

    def recover(self) -> list:
        records, clean_offset = self._store.read_records()
        # Discard any torn tail so subsequent appends start at a clean boundary.
        self._store.truncate_to(clean_offset)
        snapshot = self._load_snapshot()
        jobs = {}
        max_seq = 0
        if snapshot is not None:
            jobs = {job_id: Job(**job_data) for job_id, job_data in snapshot["jobs"].items()}
            max_seq = snapshot["max_seq"]
        for _, rec in records:
            # Record seq is globally monotonic and never resets across a WAL
            # truncation, so it is a reliable cutoff: records already covered by
            # the snapshot are skipped exactly, never re-applied.
            if rec["seq"] <= max_seq:
                continue
            self._apply(rec, jobs)
            max_seq = max(max_seq, rec["seq"])
        self._store.restore_index(jobs, max_seq)
        self._idem.rebuild(
            {job.idempotency_key: job.job_id for job in jobs.values() if job.idempotency_key}
        )
        now = self._clock()
        recovered = []
        for job in jobs.values():
            if job.status in _TERMINAL:
                continue
            self._queue.remove(job.job_id)
            job.status = "queued"
            self._queue.put(job.priority, job.job_id, enqueued_at=now)
            self._metrics.inc("recovered")
            recovered.append(job.job_id)
        return recovered

    def snapshot(self) -> int:
        with self._store.lock:
            durable = self._store.durable_offset()
            data = {
                "jobs": {job_id: job_to_dict(job) for job_id, job in self._store.all_jobs().items()},
                "idem": self._idem.as_dict(),
                "max_seq": self._store.max_seq(),
                "wal_offset": durable,
            }
            tmp = self.snapshot_path() + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.snapshot_path())
            dirfd = os.open(os.path.dirname(self.snapshot_path()) or ".", os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
            self._store.truncate()
            return durable

    def _load_snapshot(self):
        path = self.snapshot_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise RecoveryError(f"corrupt snapshot file {path!r}: {e}") from e
        if not isinstance(data, dict) or "wal_offset" not in data or "jobs" not in data:
            raise RecoveryError(f"corrupt snapshot file {path!r}: missing fields")
        return data

    def _apply(self, rec: dict, jobs: dict) -> None:
        op = rec.get("op")
        if op == "submit":
            job = Job(**rec["job"])
            jobs[job.job_id] = job
        elif op == "complete":
            job = jobs.get(rec.get("job_id"))
            if job is None:
                raise RecoveryError(f"complete record for unknown job {rec.get('job_id')!r}")
            job.status = rec.get("status", job.status)
            job.result = rec.get("result")
            job.error = rec.get("error")
            job.attempts = rec.get("attempts", job.attempts)
            job.finished_at = rec.get("finished_at")
        elif op == "cancel":
            job = jobs.get(rec.get("job_id"))
            if job is None:
                raise RecoveryError(f"cancel record for unknown job {rec.get('job_id')!r}")
            job.status = "cancelled"
            job.finished_at = rec.get("finished_at")
        else:
            raise RecoveryError(f"unknown WAL op {op!r}")
