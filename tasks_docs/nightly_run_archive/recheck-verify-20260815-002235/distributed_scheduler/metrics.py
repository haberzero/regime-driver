import threading


class Metrics:
    """Thread-safe monotonic counters.

    Keys: submitted / succeeded / failed / retried / recovered / deadline_hit.
    """

    KEYS = ("submitted", "succeeded", "failed", "retried", "recovered", "deadline_hit")

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {k: 0 for k in self.KEYS}

    def inc(self, name: str, delta: int = 1) -> None:
        if delta < 0:
            raise ValueError(f"delta must be non-negative, got {delta}")
        with self._lock:
            if name not in self._counts:
                raise ValueError(f"unknown metric: {name!r}")
            self._counts[name] += delta

    def get(self, name: str) -> int:
        with self._lock:
            if name not in self._counts:
                raise ValueError(f"unknown metric: {name!r}")
            return self._counts[name]

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._counts)
