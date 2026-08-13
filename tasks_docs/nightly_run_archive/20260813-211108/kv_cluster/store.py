"""Single-node KVStore with op-journal durability, plus the top-level
KVCluster facade that composes sharding and replication."""

import json
import os
import threading

from errors import InvalidKeyError, KeyNotFoundError, StorageFullError


class KVStore:
    """Thread-safe, in-memory key/value store with optional append-only
    op-journal for crash recovery.

    Values may be any JSON-serializable object. On set/delete the mutation is
    appended to the journal (if configured) *before* it is applied to memory,
    so the journal always reflects the latest committed state.
    """

    def __init__(self, name="kv", journal_path=None, max_size=None, fsync=False):
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if max_size is not None and (not isinstance(max_size, int) or max_size < 1):
            raise ValueError("max_size must be a positive integer or None")
        self.name = name
        self.journal_path = journal_path
        self.max_size = max_size
        self._fsync = fsync
        self.replication = False
        self._data = {}
        self._lock = threading.RLock()
        self._journal = None
        if journal_path is not None:
            parent = os.path.dirname(journal_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    # ------------------------------------------------------------------ #
    # journal plumbing
    # ------------------------------------------------------------------ #
    def _open_journal(self):
        if self.journal_path is None:
            return
        if self._journal is None or self._journal.closed:
            self._journal = open(self.journal_path, "a", encoding="utf-8")

    def _append_journal(self, op):
        if self.journal_path is None:
            return
        self._open_journal()
        line = json.dumps(op, ensure_ascii=False, separators=(",", ":")) + "\n"
        self._journal.write(line)
        self._journal.flush()
        if self._fsync:
            os.fsync(self._journal.fileno())

    def close(self):
        with self._lock:
            if self._journal is not None and not self._journal.closed:
                self._journal.flush()
                self._journal.close()
            self._journal = None

    # ------------------------------------------------------------------ #
    # validation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_key(key):
        if not isinstance(key, str) or key == "":
            raise InvalidKeyError(key)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def get(self, key):
        with self._lock:
            self._validate_key(key)
            try:
                return self._data[key]
            except KeyError:
                raise KeyNotFoundError(key)

    def set(self, key, value):
        with self._lock:
            self._validate_key(key)
            try:
                json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"value for {key!r} is not JSON-serializable: {exc}"
                ) from exc
            is_new = key not in self._data
            if is_new and self.max_size is not None and len(self._data) >= self.max_size:
                raise StorageFullError(self.max_size)
            self._append_journal({"op": "set", "key": key, "value": value})
            self._data[key] = value
            return value

    def delete(self, key):
        with self._lock:
            self._validate_key(key)
            if key not in self._data:
                raise KeyNotFoundError(key)
            self._append_journal({"op": "delete", "key": key})
            del self._data[key]
            return True

    def has(self, key):
        with self._lock:
            self._validate_key(key)
            return key in self._data

    @property
    def size(self):
        with self._lock:
            return len(self._data)

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    # ------------------------------------------------------------------ #
    # journal recovery
    # ------------------------------------------------------------------ #
    @classmethod
    def from_journal(cls, journal_path, **kwargs):
        kwargs.setdefault("name", "kv-recovered")
        store = cls(journal_path=journal_path, **kwargs)
        store.replay()
        return store

    def replay(self):
        if self.journal_path is None or not os.path.exists(self.journal_path):
            return
        with self._lock:
            with open(self.journal_path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        op = json.loads(raw)
                    except json.JSONDecodeError:
                        # Torn trailing write from a crash: ignore the partial
                        # record. Everything fully written has already been read.
                        continue
                    if op.get("op") == "set":
                        self._data[op["key"]] = op["value"]
                    elif op.get("op") == "delete":
                        self._data.pop(op["key"], None)


class KVCluster:
    """Top-level facade combining sharding (ShardManager) with optional
    per-shard primary/backup replication (ReplicaManager).

    Exposes get/set/delete/has/failover/status plus shard down/up control.
    """

    def __init__(self, shard_count, replication=True, shard_store_factory=None):
        from shard import ShardManager

        self.shard_count = shard_count
        self.replication = replication
        self._store_factory = shard_store_factory or self._default_store_factory
        self.shard_manager = ShardManager(shard_count, store_factory=self._store_factory)

    def _default_store_factory(self, shard_id):
        from replica import ReplicaManager

        if self.replication:
            return ReplicaManager(name=f"shard-{shard_id}")
        return KVStore(name=f"shard-{shard_id}")

    # -- data operations ----------------------------------------------- #
    def get(self, key):
        return self.shard_manager.get(key)

    def set(self, key, value):
        return self.shard_manager.set(key, value)

    def delete(self, key):
        return self.shard_manager.delete(key)

    def has(self, key):
        return self.shard_manager.has(key)

    @property
    def size(self):
        return sum(store.size for store in self.shard_manager.stores)

    # -- shard lifecycle ----------------------------------------------- #
    def mark_shard_down(self, shard_id):
        self.shard_manager.mark_shard_down(shard_id)

    def mark_shard_up(self, shard_id):
        self.shard_manager.mark_shard_up(shard_id)

    def is_shard_down(self, shard_id):
        return self.shard_manager.is_down(shard_id)

    def failover(self, shard_index=None):
        if shard_index is None:
            for store in self.shard_manager.stores:
                if store.replication:
                    store.failover()
            return
        self.shard_manager._validate_shard_id(shard_index)
        store = self.shard_manager.stores[shard_index]
        if not store.replication:
            raise ValueError(
                f"replication is disabled; shard {shard_index} has no failover"
            )
        store.failover()

    def status(self):
        shards = self.shard_manager.status()
        return {
            "shard_count": self.shard_count,
            "replication": self.replication,
            "shards": shards,
            "total_size": sum(sh["size"] for sh in shards),
        }
