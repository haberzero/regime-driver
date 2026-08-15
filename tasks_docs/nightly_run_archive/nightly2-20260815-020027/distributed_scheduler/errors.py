class SchedulerError(Exception):
    """Base class for all scheduler errors."""


class JobNotFoundError(SchedulerError):
    """Raised when an operation targets a job that does not exist."""


class DuplicateJobError(SchedulerError):
    """Raised when submitting a job whose idempotency key is already taken."""


class JobTimeoutError(SchedulerError):
    """Raised when a job exceeds its deadline / per-attempt timeout."""


class ExecutorFullError(SchedulerError):
    """Raised when submitting would exceed the executor's capacity."""


class RecoveryError(SchedulerError):
    """Raised when the WAL cannot be replayed (corrupt middle section)."""


class InvalidJobError(SchedulerError):
    """Raised when a job is submitted with invalid parameters."""
