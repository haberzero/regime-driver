import threading

_COUNTER_NAMES = ("submitted", "succeeded", "failed", "retried", "recovered", "deadline_hit")


class Metrics:
    """Thread-safe counters tracking the scheduler's activity.

    Every counter corresponds to one authoritative terminal transition or
    user-facing event: submitted (new jobs accepted), succeeded/failed
    (terminal execution outcomes), retried (attempts that will run again),
    recovered (jobs rolled back to queued after crash recovery) and
    deadline_hit (per-attempt timeouts).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {name: 0 for name in _COUNTER_NAMES}

    def inc(self, name, delta=1):
        if name not in self._counters:
            raise KeyError(f"unknown metric: {name!r}")
        with self._lock:
            self._counters[name] += delta

    def get(self, name):
        with self._lock:
            return self._counters[name]

    def snapshot(self):
        with self._lock:
            return dict(self._counters)
