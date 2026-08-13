"""Unified exception hierarchy for the ETL pipeline framework."""


class PipelineError(Exception):
    """Base class for all pipeline errors."""


class StageFailure(PipelineError):
    """A stage raised while the pipeline ran in fail-fast mode.

    Carries the name of the failing stage and the underlying exception
    (also available as ``__cause__``).
    """

    def __init__(self, stage_name, cause):
        super().__init__("stage %r failed: %r" % (stage_name, cause))
        self.stage_name = stage_name
        self.cause = cause


class RetryExhausted(PipelineError):
    """A RetryStage ran out of attempts without a single success."""

    def __init__(self, stage_name, last_error, attempts):
        super().__init__(
            "stage %r exhausted %d attempts; last error: %r"
            % (stage_name, attempts, last_error)
        )
        self.stage_name = stage_name
        self.last_error = last_error
        self.attempts = attempts


class RateLimitExceeded(PipelineError):
    """A rate-limited stage was asked to exceed its configured rate."""

    def __init__(self, stage_name=None, message=None):
        if message is None:
            message = "rate limit exceeded for stage %r" % (stage_name or "<unknown>")
        super().__init__(message)
        self.stage_name = stage_name


class InvalidPipelineError(PipelineError):
    """A pipeline is structurally invalid: cycle, duplicate name, bad link."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason
