"""Shared helpers for scheduler tests."""

import threading
import time


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t
        self._lock = threading.Lock()

    def __call__(self):
        return self.t

    def advance(self, dt):
        with self._lock:
            self.t += dt


def wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
