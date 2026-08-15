import threading


class IdempotencyIndex:
    """idempotency_key -> job_id mapping, rebuilt from the WAL on recovery.

    A key registered for a job in ANY state (queued/running/succeeded/failed/
    cancelled) makes a later submit with the same key a duplicate.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._map = {}

    def register(self, key: str, job_id: str) -> None:
        with self._lock:
            self._map[key] = job_id

    def lookup(self, key: str):
        with self._lock:
            return self._map.get(key)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._map

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._map)

    def rebuild(self, data: dict) -> None:
        with self._lock:
            self._map = dict(data)
