import time


class Clock:
    """Injectable clock; defaults to time.monotonic.

    Used for priority-queue aging decisions and job timestamps so tests can
    drive aging deterministically.
    """

    def __init__(self, fn=None):
        self._fn = fn if fn is not None else time.monotonic

    def __call__(self) -> float:
        return self._fn()
