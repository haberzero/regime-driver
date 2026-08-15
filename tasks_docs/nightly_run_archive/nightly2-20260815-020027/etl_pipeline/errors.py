class PipelineError(Exception):
    """Base class for all pipeline-related errors."""


class StageFailure(PipelineError):
    """Raised by Pipeline.run in fail_fast mode when a stage fails on a batch."""

    def __init__(self, stage, batch, cause=None):
        self.stage = stage
        self.batch = batch
        self.cause = cause
        super().__init__(f"stage {stage.name!r} failed on batch: {cause!r}")


class RetryExhausted(PipelineError):
    """Raised by RetryStage when all attempts fail; carries the last error."""

    def __init__(self, inner, attempts, last_error):
        self.inner = inner
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"retries exhausted after {attempts} attempt(s); "
            f"last error: {last_error!r}"
        )


class RateLimitExceeded(PipelineError):
    """Raised by RateLimitStage when on_overrun='raise' and tokens are short."""

    def __init__(self, per_sec, need_wait):
        self.per_sec = per_sec
        self.need_wait = need_wait
        super().__init__(
            f"rate limit exceeded ({per_sec}/sec); "
            f"would need to wait {need_wait:.6f}s"
        )


class InvalidPipelineError(PipelineError):
    """Raised by Pipeline.validate for cycles, duplicate names, or illegal edges."""

    def __init__(self, problems, cycle=None):
        self.problems = list(problems)
        self.cycle = cycle
        super().__init__("; ".join(self.problems) if self.problems else "invalid pipeline")
