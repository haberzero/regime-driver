import threading
from typing import Dict, Optional


class IdempotencyRegistry:
    """Thread-safe mapping of idempotency_key -> job_id.

    Registration is atomic: a concurrent submit of the same key loses exactly
    once, guaranteeing the key is never mapped twice.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._map: Dict[str, str] = {}

    def register(self, key: str, job_id: str) -> bool:
        with self._lock:
            if key in self._map:
                return False
            self._map[key] = job_id
            return True

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._map

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._map.get(key)

    def reset(self) -> None:
        with self._lock:
            self._map.clear()

    def items(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._map)
