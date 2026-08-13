"""ReplicaManager: a primary KVStore with one synchronous backup replica.

Consistency model decision: primary-write-backup synchronous replication
(write-through). A set() returns only after the backup has durably stored the
value; if the backup write fails, the primary is rolled back and a
ReplicationError is raised. This guarantees read-after-write consistency and
that failover() loses no committed write (see DESIGN.md for rationale).
"""

import threading

from errors import KeyNotFoundError, ReplicationError
from store import KVStore


class ReplicaManager:
    """Primary + 1 backup KVStore.

    All writes go to the primary first and are synchronously replicated to the
    backup under a single lock, so the backup is always a prefix of the
    primary's write history (no committed write is ever lost on failover).
    """

    def __init__(self, primary=None, backup=None, name="replica", store_factory=None):
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        self.name = name
        if store_factory is None:
            store_factory = lambda tag: KVStore(name=f"{name}-{tag}")  # noqa: E731
        self._store_factory = store_factory
        self.replication = True
        self.primary = primary if primary is not None else store_factory("primary")
        self.backup = backup if backup is not None else store_factory("backup")
        self._lock = threading.RLock()
        self._failover_epoch = 0

    # -- writes -------------------------------------------------------- #
    def set(self, key, value):
        with self._lock:
            had = self.primary.has(key)
            old = self.primary.get(key) if had else None
            self.primary.set(key, value)
            try:
                self.backup.set(key, value)
            except Exception as exc:
                rollback = self._rollback_primary(key, had, old)
                detail = f"backup write failed for {key!r}: {exc!r}"
                if rollback is not None:
                    detail += f"; rollback failed: {rollback!r}"
                raise ReplicationError(detail) from exc
            return value

    def delete(self, key):
        with self._lock:
            had = self.primary.has(key)
            if not had:
                raise KeyNotFoundError(key)
            old = self.primary.get(key)
            self.primary.delete(key)
            try:
                self.backup.delete(key)
            except Exception as exc:
                try:
                    self.primary.set(key, old)
                except Exception as restore_exc:
                    raise ReplicationError(
                        f"backup delete failed for {key!r}: {exc!r}; "
                        f"primary restore failed: {restore_exc!r}"
                    ) from exc
                raise ReplicationError(
                    f"backup delete failed for {key!r}: {exc!r}"
                ) from exc
            return True

    def _rollback_primary(self, key, had, old):
        """Restore the primary after a failed backup write.

        Returns the rollback exception (or None) so the caller can surface it;
        never swallows it silently.
        """
        try:
            if had:
                self.primary.set(key, old)
            else:
                self.primary.delete(key)
        except Exception as exc:
            return exc
        return None

    # -- reads --------------------------------------------------------- #
    def get(self, key):
        return self.primary.get(key)

    def has(self, key):
        return self.primary.has(key)

    @property
    def size(self):
        return self.primary.size

    def keys(self):
        return self.primary.keys()

    # -- failover ------------------------------------------------------ #
    def failover(self):
        """Promote the backup to primary and rebuild a fresh backup.

        Because writes are synchronously replicated, the backup is a complete
        copy of the primary, so no committed write is lost.
        """
        with self._lock:
            self._failover_epoch += 1
            new_primary = self.backup
            new_backup = self._store_factory(f"backup-epoch{self._failover_epoch}")
            for k in new_primary.keys():
                new_backup.set(k, new_primary.get(k))
            self.primary = new_primary
            self.backup = new_backup
            return self
