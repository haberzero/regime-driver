class SchedulerError(Exception):
    """Base class for all scheduler errors."""


class InvalidJobError(SchedulerError):
    """Raised when a job submission carries invalid parameters."""


class JobNotFoundError(SchedulerError):
    """Raised when a job cannot be found."""


class DuplicateJobError(SchedulerError):
    """Raised when a job_id already exists."""


class JobTimeoutError(SchedulerError):
    """Raised when a job attempt exceeds its timeout."""


class ExecutorFullError(SchedulerError):
    """Raised when the executor is at capacity (all workers busy and queue full)."""


class RecoveryError(SchedulerError):
    """Raised when recovery or durability is corrupted (non torn-tail)."""
