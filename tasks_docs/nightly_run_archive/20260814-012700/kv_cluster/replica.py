import json
import os
import threading

import store
from errors import ReplicationError


class ReplicaManager:
    def __init__(self, shard_id, journal_dir=None, limit=None, backup_limit=None, fsync=True):
        self.shard_id = shard_id
        self._lock = threading.RLock()
        self._journal_dir = journal_dir
        self._limit = limit
        self._backup_limit = backup_limit if backup_limit is not None else limit
        self._fsync = fsync
        self._gen = 0
        if self._journal_dir is not None:
            os.makedirs(self._journal_dir, exist_ok=True)
            self._gen = self._load_gen()
        self.primary = self._new_store("primary")
        self.backup = self._new_store("backup")
        self.backup.rebuild(self.primary.items())

    def _role_file(self):
        return os.path.join(self._journal_dir, f"shard{self.shard_id}_role.json")

    def _load_gen(self):
        try:
            with open(self._role_file(), "r", encoding="utf-8") as fh:
                return int(json.load(fh).get("gen", 0))
        except (OSError, ValueError):
            return 0

    def _save_gen(self):
        with open(self._role_file(), "w", encoding="utf-8") as fh:
            json.dump({"gen": self._gen}, fh)

    def _new_store(self, role):
        journal_path = None
        limit = self._limit if role == "primary" else self._backup_limit
        if self._journal_dir is not None:
            journal_path = os.path.join(
                self._journal_dir,
                f"shard{self.shard_id}_{role}.g{self._gen}.journal",
            )
        return store.KVStore(journal_path=journal_path, limit=limit, fsync=self._fsync)

    def set(self, key, value):
        with self._lock:
            old_present = self.primary.has(key)
            old_value = self.primary.get(key) if old_present else None
            self.primary.set(key, value)
            try:
                self.backup.set(key, value)
            except Exception as exc:
                self._rollback_write(key, old_present, old_value)
                raise ReplicationError(
                    f"backup write failed for key {key!r}"
                ) from exc

    def delete(self, key):
        with self._lock:
            if not self.primary.has(key):
                self.primary.delete(key)
                return
            old_value = self.primary.get(key)
            self.primary.delete(key)
            try:
                self.backup.delete(key)
            except Exception as exc:
                self._rollback_write(key, True, old_value)
                raise ReplicationError(
                    f"backup delete failed for key {key!r}"
                ) from exc

    def _rollback_write(self, key, present, old_value):
        try:
            if present:
                self.primary.set(key, old_value)
            else:
                self.primary.delete(key)
        except Exception as rollback_exc:
            raise ReplicationError(
                f"rollback failed for key {key!r}: {rollback_exc}"
            ) from rollback_exc

    def get(self, key):
        with self._lock:
            return self.primary.get(key)

    def has(self, key):
        with self._lock:
            return self.primary.has(key)

    def size(self):
        with self._lock:
            return self.primary.size()

    def backup_size(self):
        with self._lock:
            return self.backup.size()

    def backup_healthy(self):
        with self._lock:
            return dict(self.backup.items()) == dict(self.primary.items())

    def failover(self):
        with self._lock:
            old_primary = self.primary
            old_backup = self.backup
            snapshot = dict(old_backup.items())
            old_primary.close()
            old_backup.close()
            self._gen += 1
            if self._journal_dir is not None:
                self._save_gen()
            self.primary = self._new_store("primary")
            self.primary.rebuild(snapshot)
            self.backup = self._new_store("backup")
            self.backup.rebuild(snapshot)
            if self._journal_dir is not None:
                for role in ("primary", "backup"):
                    path = os.path.join(
                        self._journal_dir,
                        f"shard{self.shard_id}_{role}.g{self._gen - 1}.journal",
                    )
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def close(self):
        with self._lock:
            self.primary.close()
            self.backup.close()
