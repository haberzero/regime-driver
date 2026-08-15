class StageFailure(Exception):
    def __init__(self, stage, message=None, cause=None):
        self.stage = stage
        self.message = message if message is not None else f"stage {stage} failed"
        self.cause = cause
        super().__init__(self.message)


class RetryExhausted(StageFailure):
    def __init__(self, stage, message=None, last_error=None, attempts=None):
        self.last_error = last_error
        self.attempts = attempts
        if message is None:
            message = f"retry exhausted after {attempts} attempt(s)"
        super().__init__(stage, message=message, cause=last_error)


class RateLimitExceeded(StageFailure):
    def __init__(self, stage, per_sec, message=None):
        self.per_sec = per_sec
        if message is None:
            message = f"rate limit of {per_sec} rows/s exceeded"
        super().__init__(stage, message=message)


class InvalidPipelineError(Exception):
    def __init__(self, message, detail=None):
        self.detail = detail
        super().__init__(message)
