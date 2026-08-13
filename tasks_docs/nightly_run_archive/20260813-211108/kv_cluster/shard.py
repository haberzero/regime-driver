"""ShardManager: deterministic key->shard routing with failure isolation.

Mapping decision: simple modulo over a stable crc32 hash of the key
(see DESIGN.md for rationale and the rejected consistent-hashing option).
"""

import threading
import zlib

from errors import InvalidKeyError, ShardDownError
from store import KVStore


def _stable_hash(key):
    """Deterministic across processes (unlike builtin hash / PYTHONHASHSEED)."""
    return zlib.crc32(key.encode("utf-8"))


class ShardManager:
    """Routes each key to exactly one of ``shard_count`` underlying stores.

    A marked-down shard raises ShardDownError for every operation routed to
    it, while the remaining shards keep serving normally (failure isolation).
    """

    def __init__(self, shard_count, store_factory=None):
        if not isinstance(shard_count, int) or shard_count < 1:
            raise ValueError("shard_count must be a positive integer")
        self.shard_count = shard_count
        if store_factory is None:
            store_factory = lambda i: KVStore(name=f"shard-{i}")  # noqa: E731
        self.stores = [store_factory(i) for i in range(shard_count)]
        self._down = set()
        self._down_lock = threading.Lock()

    def shard_index(self, key):
        if not isinstance(key, str) or key == "":
            raise InvalidKeyError(key)
        return _stable_hash(key) % self.shard_count

    def _locate(self, key):
        idx = self.shard_index(key)
        with self._down_lock:
            if idx in self._down:
                raise ShardDownError(idx)
        return idx, self.stores[idx]

    # -- routed operations -------------------------------------------- #
    def get(self, key):
        _, store = self._locate(key)
        return store.get(key)

    def set(self, key, value):
        _, store = self._locate(key)
        return store.set(key, value)

    def delete(self, key):
        _, store = self._locate(key)
        return store.delete(key)

    def has(self, key):
        _, store = self._locate(key)
        return store.has(key)

    @property
    def size(self):
        return sum(store.size for store in self.stores)

    def keys(self):
        keys = []
        for store in self.stores:
            keys.extend(store.keys())
        return keys

    # -- shard lifecycle ---------------------------------------------- #
    def mark_shard_down(self, shard_id):
        self._validate_shard_id(shard_id)
        with self._down_lock:
            self._down.add(shard_id)

    def mark_shard_up(self, shard_id):
        self._validate_shard_id(shard_id)
        with self._down_lock:
            self._down.discard(shard_id)

    def is_down(self, shard_id):
        self._validate_shard_id(shard_id)
        with self._down_lock:
            return shard_id in self._down

    def _validate_shard_id(self, shard_id):
        if not isinstance(shard_id, int) or not 0 <= shard_id < self.shard_count:
            raise ValueError(f"shard id {shard_id} out of range [0,{self.shard_count})")

    def status(self):
        with self._down_lock:
            down = set(self._down)
        out = []
        for i, store in enumerate(self.stores):
            entry = {"id": i, "down": i in down, "size": store.size}
            if store.replication:
                entry["primary"] = {"alive": True, "size": store.primary.size}
                entry["backup"] = {"alive": True, "size": store.backup.size}
            out.append(entry)
        return out
