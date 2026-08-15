class SchedulerError(Exception):
    """Base class for every error raised by the scheduler subsystem."""


class JobNotFoundError(SchedulerError):
    def __init__(self, job_id):
        self.job_id = job_id
        super().__init__(f"job not found: {job_id!r}")


class DuplicateJobError(SchedulerError):
    def __init__(self, idempotency_key, existing_job_id):
        self.idempotency_key = idempotency_key
        self.existing_job_id = existing_job_id
        super().__init__(
            f"a job with idempotency_key {idempotency_key!r} already exists "
            f"as job {existing_job_id!r}"
        )


class JobTimeoutError(SchedulerError):
    def __init__(self, job_id, timeout):
        self.job_id = job_id
        self.timeout = timeout
        super().__init__(f"job {job_id!r} exceeded its timeout of {timeout}s")


class ExecutorFullError(SchedulerError):
    def __init__(self, job_id, pool_size):
        self.job_id = job_id
        self.pool_size = pool_size
        super().__init__(
            f"executor has no free worker (pool_size={pool_size}); "
            f"cannot submit job {job_id!r}"
        )


class RecoveryError(SchedulerError):
    pass


class InvalidJobError(SchedulerError):
    pass
