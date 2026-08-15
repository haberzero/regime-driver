import time

from errors import RateLimitExceeded, RetryExhausted


class Stage:
    """Base class for pipeline stages."""

    def __init__(self, name=None):
        self.name = name

    def run(self, rows):
        raise NotImplementedError


class TransformStage(Stage):
    """Applies fn(rows)->rows to each batch."""

    def __init__(self, fn, name=None):
        super().__init__(name)
        self.fn = fn

    def run(self, rows):
        return self.fn(rows)


class FilterStage(Stage):
    """Keeps only rows for which pred(row) is truthy."""

    def __init__(self, pred, name=None):
        super().__init__(name)
        self.pred = pred

    def run(self, rows):
        return [row for row in rows if self.pred(row)]


class RetryStage(Stage):
    """Runs inner up to retries+1 times with exponential backoff."""

    def __init__(self, inner, retries=2, backoff_base=0.0, name=None, sleeper=time.sleep):
        if retries < 0:
            raise ValueError("retries must be >= 0")
        if backoff_base < 0:
            raise ValueError("backoff_base must be >= 0")
        super().__init__(name)
        self.inner = inner
        self.retries = retries
        self.backoff_base = backoff_base
        self._sleeper = sleeper

    def run(self, rows):
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                return self.inner.run(rows)
            except Exception as exc:
                last_error = exc
                if attempt == self.retries:
                    raise RetryExhausted(self, attempt + 1, last_error) from last_error
                if self.backoff_base > 0:
                    self._sleeper(self.backoff_base * (2 ** attempt))


class RateLimitStage(Stage):
    """Token-bucket rate limiter; blocks by default or raises when on_overrun='raise'."""

    def __init__(self, per_sec, capacity=None, on_overrun="wait", name=None,
                 clock=time.monotonic, sleeper=time.sleep):
        if per_sec <= 0:
            raise ValueError("per_sec must be > 0")
        if on_overrun not in ("wait", "raise"):
            raise ValueError("on_overrun must be 'wait' or 'raise'")
        super().__init__(name)
        self.per_sec = per_sec
        self.capacity = per_sec if capacity is None else capacity
        if self.capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.on_overrun = on_overrun
        self._clock = clock
        self._sleeper = sleeper
        self._tokens = float(self.capacity)
        self._last = self._clock()

    def _consume(self, count=1):
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.per_sec)
        self._last = now
        if self._tokens >= count:
            self._tokens -= count
            return
        need_wait = (count - self._tokens) / self.per_sec
        if self.on_overrun == "raise":
            raise RateLimitExceeded(self.per_sec, need_wait)
        self._sleeper(need_wait)
        self._tokens = 0.0
        self._last = self._clock()

    def run(self, rows):
        result = []
        for row in rows:
            self._consume(1)
            result.append(row)
        return result


class BatchSink(Stage):
    """Buffers rows and appends full batches to self.rows; flush() is idempotent."""

    def __init__(self, limit, name=None):
        if limit <= 0:
            raise ValueError("limit must be > 0")
        super().__init__(name)
        self.limit = limit
        self.rows = []
        self._buffer = []

    @property
    def buffered(self):
        return len(self._buffer)

    def run(self, rows):
        self._buffer.extend(rows)
        while len(self._buffer) >= self.limit:
            self.rows.append(self._buffer[: self.limit])
            self._buffer = self._buffer[self.limit:]
        return []

    def flush(self):
        if self._buffer:
            self.rows.append(list(self._buffer))
            self._buffer = []
