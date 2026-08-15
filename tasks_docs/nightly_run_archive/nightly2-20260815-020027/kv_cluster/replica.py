"""Primary/backup replication with write-through and failover."""

import threading

from errors import KeyNotFoundError, ReplicationError
from store import KVStore


class ReplicaManager:
    """Synchronous primary/backup replication for a single key-value store.

    set/delete are applied to the primary and then written through to the
    backup; if the backup write fails the primary change is rolled back and
    ReplicationError is raised, leaving the cluster usable.
    """

    def __init__(self, primary, backup, backup_factory=None):
        if not isinstance(primary, KVStore) or not isinstance(backup, KVStore):
            raise TypeError("primary and backup must be KVStore instances")
        self._primary = primary
        self._backup = backup
        self._backup_factory = backup_factory if backup_factory is not None else KVStore
        self._lock = threading.RLock()

    @property
    def primary(self):
        return self._primary

    @property
    def backup(self):
        return self._backup

    def set(self, key, value):
        with self._lock:
            had_key = self._primary.has(key)
            old_value = self._primary.get(key) if had_key else None
            self._primary.set(key, value)
            try:
                self._backup.set(key, value)
            except Exception as exc:
                if had_key:
                    self._primary.set(key, old_value)
                else:
                    self._primary.delete(key)
                raise ReplicationError(
                    "backup write failed for key %r: %s" % (key, exc)
                ) from exc

    def delete(self, key):
        with self._lock:
            if not self._primary.has(key):
                raise KeyNotFoundError("key %r not found" % (key,))
            old_value = self._primary.get(key)
            self._primary.delete(key)
            try:
                self._backup.delete(key)
            except Exception as exc:
                self._primary.set(key, old_value)
                raise ReplicationError(
                    "backup delete failed for key %r: %s" % (key, exc)
                ) from exc

    def get(self, key):
        return self._primary.get(key)

    def has(self, key):
        return self._primary.has(key)

    @property
    def size(self):
        return self._primary.size

    def keys(self):
        return self._primary.keys()

    def backup_healthy(self):
        with self._lock:
            return self._primary.size == self._backup.size

    def failover(self):
        with self._lock:
            new_primary = self._backup
            new_backup = self._backup_factory()
            new_backup.copy_from(new_primary)
            self._primary.close()
            self._primary = new_primary
            self._backup = new_backup

    def close(self):
        with self._lock:
            self._primary.close()
            self._backup.close()
