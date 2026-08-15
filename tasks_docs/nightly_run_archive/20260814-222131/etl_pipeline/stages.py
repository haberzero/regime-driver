import time

from errors import RateLimitExceeded, RetryExhausted, StageFailure


class Stage:
    def __init__(self, name=None):
        self.name = name

    def run(self, rows):
        raise NotImplementedError


class TransformStage(Stage):
    def __init__(self, fn, name=None):
        super().__init__(name)
        if not callable(fn):
            raise TypeError("fn must be callable")
        self.fn = fn

    def run(self, rows):
        return self.fn(rows)


class FilterStage(Stage):
    def __init__(self, pred, name=None):
        super().__init__(name)
        if not callable(pred):
            raise TypeError("pred must be callable")
        self.pred = pred

    def run(self, rows):
        return [row for row in rows if self.pred(row)]


class RetryStage(Stage):
    def __init__(self, inner, retries, backoff_base, retry_on=StageFailure, name=None,
                 sleep=time.sleep):
        super().__init__(name)
        if not isinstance(inner, Stage):
            raise TypeError("inner must be a Stage")
        if retries < 0:
            raise ValueError(f"retries must be >= 0, got {retries}")
        if backoff_base < 0:
            raise ValueError(f"backoff_base must be >= 0, got {backoff_base}")
        self.inner = inner
        self.retries = retries
        self.backoff_base = backoff_base
        self.retry_on = retry_on
        self._sleep = sleep

    def run(self, rows):
        attempts = 0
        while True:
            attempts += 1
            try:
                return self.inner.run(rows)
            except self.retry_on as exc:
                if attempts > self.retries:
                    raise RetryExhausted(
                        self.name, last_error=exc, attempts=attempts
                    ) from exc
                self._sleep(self.backoff_base * (2 ** (attempts - 1)))
            except Exception as exc:
                raise StageFailure(
                    self.name, "non-retryable failure", exc
                ) from exc


class RateLimitStage(Stage):
    def __init__(self, per_sec, burst=None, on_limit="wait", name=None,
                 now=time.monotonic, sleep=time.sleep):
        super().__init__(name)
        if per_sec <= 0:
            raise ValueError(f"per_sec must be > 0, got {per_sec}")
        if burst is not None and burst <= 0:
            raise ValueError(f"burst must be > 0, got {burst}")
        if on_limit not in ("wait", "raise"):
            raise ValueError(f"on_limit must be 'wait' or 'raise', got {on_limit!r}")
        self.per_sec = per_sec
        self.burst = burst if burst is not None else max(1, int(per_sec))
        self.on_limit = on_limit
        self._now = now
        self._sleep = sleep
        self._tokens = float(self.burst)
        self._last_refill = now()

    def run(self, rows):
        passed = []
        for row in rows:
            now = self._now()
            self._tokens = min(
                self.burst, self._tokens + (now - self._last_refill) * self.per_sec
            )
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                passed.append(row)
                continue
            if self.on_limit == "raise":
                raise RateLimitExceeded(self.name, self.per_sec)
            self._sleep((1.0 - self._tokens) / self.per_sec)
            now = self._now()
            self._tokens = min(
                self.burst, self._tokens + (now - self._last_refill) * self.per_sec
            )
            self._last_refill = now
            self._tokens -= 1.0
            passed.append(row)
        return passed


class BatchSink(Stage):
    def __init__(self, limit, name=None):
        super().__init__(name)
        if limit <= 0:
            raise ValueError(f"limit must be > 0, got {limit}")
        self.limit = limit
        self.pending = []
        self.data = []

    def run(self, rows):
        self.pending.extend(rows)
        if len(self.pending) >= self.limit:
            self.flush()
        return []

    def flush(self):
        if not self.pending:
            return 0
        moved = len(self.pending)
        self.data.extend(self.pending)
        self.pending = []
        return moved
