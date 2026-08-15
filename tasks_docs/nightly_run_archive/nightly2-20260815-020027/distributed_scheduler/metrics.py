import threading
from typing import Dict

COUNTERS = ("submitted", "succeeded", "failed", "retried", "recovered", "deadline_hit")


class Metrics:
    """Thread-safe named counters."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {name: 0 for name in COUNTERS}

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] += n

    def get(self, name: str) -> int:
        with self._lock:
            return self._counters[name]

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)
