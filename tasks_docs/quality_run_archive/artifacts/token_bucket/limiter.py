import threading
import time


class TokenBucket:
    def __init__(self, capacity, refill_rate, clock=time.monotonic):
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if refill_rate < 0:
            raise ValueError(f"refill_rate must be non-negative, got {refill_rate}")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._clock = clock
        self._tokens = float(capacity)
        self._last_refill = clock()
        self._lock = threading.Lock()
        self._allowed = 0
        self._denied = 0

    def _refill(self, now):
        if self.refill_rate == 0:
            return
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        gained = elapsed * self.refill_rate
        if gained > 0:
            self._tokens = min(self.capacity, self._tokens + gained)
            self._last_refill = now

    def allow(self):
        with self._lock:
            self._refill(self._clock())
            if self._tokens >= 1:
                self._tokens -= 1
                self._allowed += 1
                return True
            self._denied += 1
            return False

    @property
    def total_allowed(self):
        with self._lock:
            return self._allowed

    @property
    def total_denied(self):
        with self._lock:
            return self._denied

    def stats(self):
        with self._lock:
            return {"total_allowed": self._allowed, "total_denied": self._denied}
