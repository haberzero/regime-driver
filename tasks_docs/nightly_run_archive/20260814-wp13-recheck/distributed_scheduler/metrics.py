"""Thread-safe counters for scheduler statistics."""

import threading

COUNT_KEYS = (
    "submitted",
    "succeeded",
    "failed",
    "retried",
    "recovered",
    "deadline_hit",
)


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {key: 0 for key in COUNT_KEYS}

    def inc(self, name, n=1):
        with self._lock:
            self._counts[name] += n

    def get(self, name):
        with self._lock:
            return self._counts[name]

    def snapshot(self):
        with self._lock:
            return dict(self._counts)

    def set_all(self, counts):
        with self._lock:
            for key in COUNT_KEYS:
                self._counts[key] = counts.get(key, 0)
