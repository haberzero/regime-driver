import threading
import time


class LRUCache:
    def __init__(self, capacity, ttl=None):
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if ttl is not None and ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        self._capacity = capacity
        self._ttl = ttl
        self._entries = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _expired(self, last_access):
        if self._ttl is None:
            return False
        return time.monotonic() - last_access > self._ttl

    def get(self, key, default=None):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default
            value, last_access = entry
            if self._expired(last_access):
                self._misses += 1
                return default
            del self._entries[key]
            self._entries[key] = (value, time.monotonic())
            self._hits += 1
            return value

    def set(self, key, value):
        with self._lock:
            now = time.monotonic()
            if key in self._entries:
                del self._entries[key]
                self._entries[key] = (value, now)
                return
            if len(self._entries) == self._capacity:
                oldest = next(iter(self._entries))
                del self._entries[oldest]
            self._entries[key] = (value, now)

    def has(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return False
            _, last_access = entry
            if self._expired(last_access):
                self._misses += 1
                return False
            self._hits += 1
            return True

    def size(self):
        with self._lock:
            return len(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()

    @property
    def hits(self):
        with self._lock:
            return self._hits

    @property
    def misses(self):
        with self._lock:
            return self._misses

    def stats(self):
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total else 0.0
            return {"hits": self._hits, "misses": self._misses, "hit_rate": hit_rate}
