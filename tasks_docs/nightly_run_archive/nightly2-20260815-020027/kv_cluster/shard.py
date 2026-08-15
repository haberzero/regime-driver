"""Deterministic key-to-shard routing with per-shard fault isolation."""

import hashlib
import threading

from errors import InvalidKeyError, ShardDownError


class ShardManager:
    """Routes keys to shard stores using a deterministic modulo hash.

    A shard that is marked down rejects every access to its keys with
    ShardDownError while all other shards keep serving normally.
    """

    def __init__(self, shard_count, store_factory):
        if not isinstance(shard_count, int) or shard_count <= 0:
            raise ValueError("shard_count must be a positive integer")
        self._shard_count = shard_count
        self._stores = [store_factory(shard_id) for shard_id in range(shard_count)]
        self._down = set()
        self._lock = threading.RLock()

    @staticmethod
    def shard_id_for(key, shard_count):
        if not isinstance(key, str) or not key:
            raise InvalidKeyError("key must be a non-empty string, got %r" % (key,))
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % shard_count

    @property
    def shard_count(self):
        return self._shard_count

    def _check_shard(self, shard_id):
        if (
            not isinstance(shard_id, int)
            or shard_id < 0
            or shard_id >= self._shard_count
        ):
            raise ValueError("invalid shard id %r (shard_count=%d)" % (shard_id, self._shard_count))

    def _route(self, key):
        shard_id = self.shard_id_for(key, self._shard_count)
        with self._lock:
            if shard_id in self._down:
                raise ShardDownError("shard %d is down" % shard_id)
        return shard_id

    def get(self, key):
        return self._stores[self._route(key)].get(key)

    def set(self, key, value):
        return self._stores[self._route(key)].set(key, value)

    def delete(self, key):
        return self._stores[self._route(key)].delete(key)

    def has(self, key):
        return self._stores[self._route(key)].has(key)

    def mark_shard_down(self, shard_id):
        self._check_shard(shard_id)
        with self._lock:
            self._down.add(shard_id)

    def mark_shard_up(self, shard_id):
        self._check_shard(shard_id)
        with self._lock:
            self._down.discard(shard_id)

    def get_store(self, shard_id):
        self._check_shard(shard_id)
        return self._stores[shard_id]

    def shard_status(self):
        status = {}
        for shard_id in range(self._shard_count):
            with self._lock:
                down = shard_id in self._down
            status[shard_id] = {"down": down, "size": self._stores[shard_id].size}
        return status
