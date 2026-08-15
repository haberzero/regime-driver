"""Single-node key-value store with an append-only op journal, plus the KVCluster facade."""

import json
import os
import re
import threading

from errors import InvalidKeyError, KeyNotFoundError, StorageFullError


class KVStore:
    """Thread-safe in-memory key-value store.

    Values must be JSON-serializable. Every mutation is appended to an
    optional append-only op journal; committed writes can be recovered after
    a process crash by replaying the journal on startup.
    """

    def __init__(self, journal_path=None, max_size=None, durable=True):
        if max_size is not None and (not isinstance(max_size, int) or max_size < 0):
            raise ValueError("max_size must be a non-negative integer")
        self._data = {}
        self._lock = threading.RLock()
        self._journal_path = journal_path
        self._max_size = max_size
        self._durable = durable
        self._journal_fh = None
        self._recover()
        if journal_path is not None:
            parent = os.path.dirname(os.path.abspath(journal_path))
            os.makedirs(parent, exist_ok=True)
            self._journal_fh = open(journal_path, "a", encoding="utf-8")

    @property
    def journal_path(self):
        return self._journal_path

    @staticmethod
    def _validate_key(key):
        if not isinstance(key, str) or not key:
            raise InvalidKeyError("key must be a non-empty string, got %r" % (key,))

    @staticmethod
    def _validate_value(value):
        try:
            json.dumps(value)
        except TypeError as exc:
            raise ValueError("value must be JSON-serializable: %s" % (exc,)) from exc

    def get(self, key):
        self._validate_key(key)
        with self._lock:
            try:
                return self._data[key]
            except KeyError:
                raise KeyNotFoundError("key %r not found" % (key,))

    def set(self, key, value):
        self._validate_key(key)
        self._validate_value(value)
        with self._lock:
            if (
                self._max_size is not None
                and key not in self._data
                and len(self._data) >= self._max_size
            ):
                raise StorageFullError("store capacity %d reached" % self._max_size)
            self._journal({"op": "set", "key": key, "value": value})
            self._data[key] = value

    def delete(self, key):
        self._validate_key(key)
        with self._lock:
            if key not in self._data:
                raise KeyNotFoundError("key %r not found" % (key,))
            self._journal({"op": "delete", "key": key})
            del self._data[key]

    def has(self, key):
        self._validate_key(key)
        with self._lock:
            return key in self._data

    @property
    def size(self):
        with self._lock:
            return len(self._data)

    def keys(self):
        with self._lock:
            return list(self._data)

    def copy_from(self, other):
        with self._lock, other._lock:
            for key, value in other._data.items():
                self._journal({"op": "set", "key": key, "value": value})
                self._data[key] = value

    def close(self):
        with self._lock:
            if self._journal_fh is not None:
                self._journal_fh.close()
                self._journal_fh = None

    def _recover(self):
        if self._journal_path is None or not os.path.exists(self._journal_path):
            return
        with open(self._journal_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if index == len(lines) - 1:
                try:
                    self._apply(json.loads(stripped))
                except (KeyError, ValueError):
                    pass
            else:
                self._apply(json.loads(stripped))

    def _apply(self, op):
        op_type = op.get("op")
        key = op.get("key")
        if op_type == "set":
            self._data[key] = op["value"]
        elif op_type == "delete":
            self._data.pop(key, None)
        else:
            raise ValueError("unknown journal op %r" % (op_type,))

    def _journal(self, op):
        if self._journal_fh is None:
            return
        self._journal_fh.write(json.dumps(op, ensure_ascii=False) + "\n")
        if self._durable:
            self._journal_fh.flush()
            os.fsync(self._journal_fh.fileno())


class KVCluster:
    """Top-level facade combining sharding and optional primary/backup replication."""

    def __init__(self, shard_count, replication=True, journal_dir=None, max_size=None, durable=True):
        from replica import ReplicaManager
        from shard import ShardManager

        if not isinstance(shard_count, int) or shard_count <= 0:
            raise ValueError("shard_count must be a positive integer")
        self._shard_count = shard_count
        self._replication = replication
        self._journal_dir = journal_dir
        self._max_size = max_size
        self._durable = durable
        self._backup_gens = {}
        self._ReplicaManager = ReplicaManager
        self._shards = ShardManager(shard_count, self._store_factory)

    def get(self, key):
        return self._shards.get(key)

    def set(self, key, value):
        return self._shards.set(key, value)

    def delete(self, key):
        return self._shards.delete(key)

    def has(self, key):
        return self._shards.has(key)

    def failover(self, shard_id):
        if not self._replication:
            raise ValueError("failover requires replication, but replication is disabled")
        manager = self._shards.get_store(shard_id)
        manager.failover()
        self._save_shard_roles(shard_id, manager.primary.journal_path, manager.backup.journal_path)

    def mark_shard_down(self, shard_id):
        self._shards.mark_shard_down(shard_id)

    def mark_shard_up(self, shard_id):
        self._shards.mark_shard_up(shard_id)

    @property
    def shard_count(self):
        return self._shard_count

    @property
    def replication_enabled(self):
        return self._replication

    def status(self):
        shards = self._shards.shard_status()
        for shard_id in shards:
            manager = self._shards.get_store(shard_id)
            shards[shard_id]["replication"] = self._replication
            if self._replication:
                shards[shard_id]["primary_size"] = manager.primary.size
                shards[shard_id]["backup_size"] = manager.backup.size
                shards[shard_id]["backup_healthy"] = manager.backup_healthy()
        return {
            "shard_count": self._shard_count,
            "replication": self._replication,
            "shards": shards,
        }

    def close(self):
        for shard_id in range(self._shard_count):
            self._shards.get_store(shard_id).close()

    def _store_factory(self, shard_id):
        if not self._replication:
            path = self._journal_for(shard_id, "single", 0)
            return KVStore(journal_path=path, max_size=self._max_size, durable=self._durable)
        primary_path, backup_path = self._shard_roles(shard_id)
        primary = KVStore(journal_path=primary_path, max_size=self._max_size, durable=self._durable)
        backup = KVStore(journal_path=backup_path, max_size=self._max_size, durable=self._durable)
        self._backup_gens[shard_id] = self._backup_gen_from_path(backup_path)
        return self._ReplicaManager(
            primary,
            backup,
            backup_factory=lambda: self._fresh_backup(shard_id),
        )

    def _fresh_backup(self, shard_id):
        self._backup_gens[shard_id] = self._backup_gens.get(shard_id, 0) + 1
        path = self._journal_for(shard_id, "backup", self._backup_gens[shard_id])
        return KVStore(journal_path=path, max_size=self._max_size, durable=self._durable)

    def _shard_roles(self, shard_id):
        meta_path = self._meta_path(shard_id)
        if meta_path is not None and os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as fh:
                roles = json.load(fh)
            return roles["primary"], roles["backup"]
        return self._journal_for(shard_id, "primary", 0), self._journal_for(shard_id, "backup", 0)

    def _save_shard_roles(self, shard_id, primary_path, backup_path):
        meta_path = self._meta_path(shard_id)
        if meta_path is None:
            return
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump({"primary": primary_path, "backup": backup_path}, fh)

    def _meta_path(self, shard_id):
        if self._journal_dir is None:
            return None
        return os.path.join(self._journal_dir, "shard_%d.meta" % shard_id)

    def _journal_for(self, shard_id, role, generation):
        if self._journal_dir is None:
            return None
        return os.path.join(self._journal_dir, "shard_%d_%s_%d.log" % (shard_id, role, generation))

    @staticmethod
    def _backup_gen_from_path(path):
        if not path:
            return 0
        match = re.search(r"_backup_(\d+)\.log$", path)
        return int(match.group(1)) if match else 0
