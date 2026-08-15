from errors import DuplicateJobError


class IdempotencyRegistry:
    """Encapsulates the idempotency policy backed by the job store.

    A submit whose ``idempotency_key`` already exists in *any* state is a
    duplicate and is rejected without creating a new job. The key stays
    reserved forever (even after the job reaches a terminal state), so after
    crash recovery a completed idempotent job can never be submitted again
    and is never re-executed.
    """

    def __init__(self, store):
        self._store = store

    def precheck(self, job):
        """Raise DuplicateJobError if ``job.idempotency_key`` already exists.

        Called from inside the store's insert critical section so the
        check-and-insert pair is atomic under concurrent submits.
        """
        if job.idempotency_key is None:
            return
        existing = self._store.get_by_key(job.idempotency_key)
        if existing is not None:
            raise DuplicateJobError(job.idempotency_key, existing.job_id)

    def get_by_key(self, key):
        return self._store.get_by_key(key)

    def keys(self):
        return self._store.idempotency_keys()
