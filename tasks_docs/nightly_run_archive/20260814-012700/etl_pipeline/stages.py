"""Standard ETL stage implementations.

Each stage operates on a batch of rows (``run(rows) -> rows``). Stages are
composable and can be wired together by :class:`~pipeline.Pipeline`.
"""

import time

from errors import RateLimitExceeded, RetryExhausted


class Stage:
    """Base class for all pipeline stages."""

    def __init__(self, name=None):
        self.name = name

    def run(self, rows):
        raise NotImplementedError


class TransformStage(Stage):
    """Applies ``fn(rows) -> rows`` to each batch of rows."""

    def __init__(self, fn, name=None):
        super().__init__(name)
        if not callable(fn):
            raise TypeError("fn must be callable")
        self.fn = fn

    def run(self, rows):
        return self.fn(rows)


class FilterStage(Stage):
    """Keeps only the rows for which ``pred(row)`` is truthy."""

    def __init__(self, pred, name=None):
        super().__init__(name)
        if not callable(pred):
            raise TypeError("pred must be callable")
        self.pred = pred

    def run(self, rows):
        return [row for row in rows if self.pred(row)]


class RetryStage(Stage):
    """Runs ``inner`` retrying with exponential backoff on failure.

    A run is tried once, then up to ``retries`` times more, waiting
    ``backoff_base * 2 ** attempt`` between attempts. If every attempt fails,
    :class:`errors.RetryExhausted` is raised carrying the last error.
    ``sleep_fn`` is injectable to keep tests fast and deterministic.
    """

    def __init__(self, inner, retries, backoff_base=1.0, sleep_fn=time.sleep, name=None):
        super().__init__(name)
        if not isinstance(inner, Stage):
            raise TypeError("inner must be a Stage instance")
        if not isinstance(retries, int) or retries < 0:
            raise ValueError("retries must be a non-negative int")
        if backoff_base < 0:
            raise ValueError("backoff_base must be >= 0")
        self.inner = inner
        self.retries = retries
        self.backoff_base = backoff_base
        self.sleep_fn = sleep_fn
        self.attempts = 0
        self.last_error = None

    def run(self, rows):
        self.attempts = 0
        attempt = 0
        while True:
            try:
                return self.inner.run(rows)
            except Exception as exc:
                self.attempts += 1
                self.last_error = exc
                if attempt >= self.retries:
                    raise RetryExhausted(
                        self.name or self.inner.name or "<retry>", exc, self.attempts
                    ) from exc
                self.sleep_fn(self.backoff_base * (2 ** attempt))
                attempt += 1


class RateLimitStage(Stage):
    """Token-bucket rate limiter over the rows flowing through it.

    ``per_sec`` tokens are replenished per second; up to ``burst`` tokens can
    be spent instantly (default burst is one full second's worth). When the
    bucket is empty the stage waits for the next token, unless
    ``raise_on_limit=True`` is set, in which case
    :class:`errors.RateLimitExceeded` is raised instead.

    Pass an injectable ``clock`` (a ``callable() -> float``) to test the
    throttling behaviour deterministically.
    """

    def __init__(self, per_sec, burst=None, raise_on_limit=False, clock=None, name=None):
        super().__init__(name)
        if per_sec <= 0:
            raise ValueError("per_sec must be positive")
        if burst is not None and burst <= 0:
            raise ValueError("burst must be positive")
        self.per_sec = float(per_sec)
        self.burst = float(burst) if burst is not None else self.per_sec
        self.raise_on_limit = raise_on_limit
        self.consumed_at = []

        self._fake = clock is not None
        if self._fake:
            self._sim = clock()
        else:
            self._sim = None
        self._last = self._now()
        self.tokens = self.burst

    def _now(self):
        return self._sim if self._fake else time.monotonic()

    def _sleep(self, seconds):
        if self._fake:
            self._sim += seconds
        else:
            time.sleep(seconds)
        self._last = self._now()

    def _acquire(self):
        now = self._now()
        self.tokens = min(
            self.burst, self.tokens + max(0.0, now - self._last) * self.per_sec
        )
        self._last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            self.consumed_at.append(now)
            return
        wait = (1.0 - self.tokens) / self.per_sec
        if self.raise_on_limit:
            raise RateLimitExceeded(self.name)
        self._sleep(wait)
        self.tokens = 0.0
        self.consumed_at.append(self._now())

    def run(self, rows):
        for _row in rows:
            self._acquire()
        return rows


class BatchSink(Stage):
    """In-memory sink that commits rows in ``limit``-sized batches.

    ``run`` commits only full batches; ``flush`` commits whatever is left
    buffered. ``flush`` is idempotent: calling it with an empty buffer is a
    no-op, so it never duplicates rows.
    """

    def __init__(self, limit, name=None):
        super().__init__(name)
        if limit <= 0:
            raise ValueError("limit must be positive")
        self.limit = limit
        self._buffer = []
        self._committed = []

    @property
    def rows(self):
        """Committed rows (a copy)."""
        return list(self._committed)

    def run(self, rows):
        self._buffer.extend(rows)
        while len(self._buffer) >= self.limit:
            self._committed.extend(self._buffer[: self.limit])
            self._buffer = self._buffer[self.limit :]
        return []

    def flush(self):
        """Commit any buffered rows; returns the number committed (0 if none)."""
        if not self._buffer:
            return 0
        flushed = len(self._buffer)
        self._committed.extend(self._buffer)
        self._buffer = []
        return flushed
