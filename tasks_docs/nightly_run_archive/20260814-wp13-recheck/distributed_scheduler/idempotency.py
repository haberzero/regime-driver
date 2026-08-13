"""Idempotency-key policy.

A job may carry an ``idempotency_key``. Submitting a second job with a key
already registered to any existing job raises ``DuplicateJobError`` without
creating a new job. The key -> job mapping lives in the job store and is
rebuilt on crash replay, so the same key never maps to two jobs and a job
that reached a terminal ``succeeded`` state is never re-executed.
"""

from errors import DuplicateJobError
from job_store import SUCCEEDED


class Idempotency:
    def __init__(self, store):
        self._store = store

    def check_submit(self, key):
        """Raise DuplicateJobError if ``key`` already belongs to a job."""
        if key is None:
            return None
        existing = self._store.get_by_key(key)
        if existing is not None:
            raise DuplicateJobError(
                "idempotency_key {!r} already registered to job {!r}".format(
                    key, existing.job_id),
                job_id=existing.job_id,
            )
        return None

    def lookup(self, key):
        if key is None:
            return None
        return self._store.get_by_key(key)

    def is_completed(self, job):
        return job is not None and job.state == SUCCEEDED
