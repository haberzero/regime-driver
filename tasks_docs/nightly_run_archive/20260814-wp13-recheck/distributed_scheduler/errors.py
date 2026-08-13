"""Unified exception hierarchy for the distributed task scheduler."""


class JobError(Exception):
    """Base class for all scheduler errors."""


class JobNotFoundError(JobError):
    """Raised when an operation references a job id that does not exist."""

    def __init__(self, job_id):
        self.job_id = job_id
        super().__init__("job {!r} not found".format(job_id))


class DuplicateJobError(JobError):
    """Raised when submitting a job whose idempotency_key already exists."""

    def __init__(self, message, job_id=None):
        self.job_id = job_id
        super().__init__(message)


class JobTimeoutError(JobError):
    """Raised when a job exceeds its per-execution timeout."""


class ExecutorFullError(JobError):
    """Raised when the executor's pending queue is at capacity."""


class RecoveryError(JobError):
    """Raised when a crash-recovery operation fails or is misused."""


class InvalidJobError(JobError):
    """Raised when job parameters are invalid."""
