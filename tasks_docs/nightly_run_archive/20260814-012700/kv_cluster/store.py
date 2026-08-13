import json
import os
import threading
from typing import Any, Dict, Iterable, Tuple

from errors import InvalidKeyError, KeyNotFoundError, StorageFullError

_MISSING = object()


def _validate_key(key: Any) -> None:
    if not isinstance(key, str) or key == "":
        raise InvalidKeyError(f"key must be a non-empty string, got {key!r}")


class KVStore:
    def __init__(self, journal_path=None, limit=None, fsync=True):
        if limit is not None and limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit!r}")
        self._limit = limit
        self._fsync = fsync
        self._data: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._journal_path = None
        self._journal_fh = None
        if journal_path is not None:
            self._journal_path = os.fspath(journal_path)
            os.makedirs(os.path.dirname(self._journal_path) or ".", exist_ok=True)
            self._open_journal()
            self._recover()

    def _open_journal(self):
        self._journal_fh = open(self._journal_path, "a", encoding="utf-8")

    def _recover(self):
        try:
            with open(self._journal_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("op") == "set":
                        self._data[rec["key"]] = rec["value"]
                    elif rec.get("op") == "delete":
                        self._data.pop(rec["key"], None)
        except FileNotFoundError:
            pass

    def _append(self, line: str) -> None:
        if self._journal_fh is None:
            return
        self._journal_fh.write(line + "\n")
        self._journal_fh.flush()
        if self._fsync:
            os.fsync(self._journal_fh.fileno())

    @staticmethod
    def _encode(op: str, key: str, value: Any = None) -> str:
        rec = {"op": op, "key": key}
        if op == "set":
            rec["value"] = value
        return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))

    def get(self, key):
        _validate_key(key)
        with self._lock:
            try:
                return self._data[key]
            except KeyError:
                raise KeyNotFoundError(key)

    def set(self, key, value):
        _validate_key(key)
        try:
            line = self._encode("set", key, value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"value must be JSON-serializable for key {key!r}"
            ) from exc
        with self._lock:
            present = key in self._data
            if not present and self._limit is not None and len(self._data) >= self._limit:
                raise StorageFullError(f"storage full, limit={self._limit}")
            old = self._data.get(key, _MISSING)
            self._data[key] = value
            try:
                self._append(line)
            except Exception:
                if old is _MISSING:
                    self._data.pop(key, None)
                else:
                    self._data[key] = old
                raise

    def delete(self, key):
        _validate_key(key)
        line = self._encode("delete", key)
        with self._lock:
            if key not in self._data:
                raise KeyNotFoundError(key)
            old = self._data.pop(key)
            try:
                self._append(line)
            except Exception:
                self._data[key] = old
                raise

    def has(self, key):
        _validate_key(key)
        with self._lock:
            return key in self._data

    def size(self):
        with self._lock:
            return len(self._data)

    def keys(self):
        with self._lock:
            return list(self._data)

    def items(self):
        with self._lock:
            return list(self._data.items())

    def rebuild(self, items: Iterable[Tuple[str, Any]]) -> None:
        data = dict(items)
        with self._lock:
            self._data = data
            if self._journal_path is None:
                return
            if self._journal_fh is not None:
                self._journal_fh.close()
            with open(self._journal_path, "w", encoding="utf-8") as fh:
                for key, value in self._data.items():
                    fh.write(self._encode("set", key, value) + "\n")
                fh.flush()
                if self._fsync:
                    os.fsync(fh.fileno())
            self._open_journal()

    def close(self):
        with self._lock:
            if self._journal_fh is not None:
                self._journal_fh.close()
                self._journal_fh = None


class KVCluster:
    def __init__(
        self,
        shard_count,
        replication=True,
        journal_dir=None,
        limit=None,
        backup_limit=None,
        fsync=True,
    ):
        import shard

        self.shard_count = shard_count
        self.replication = replication
        self._manager = shard.ShardManager(
            shard_count,
            replication=replication,
            journal_dir=journal_dir,
            limit=limit,
            backup_limit=backup_limit,
            fsync=fsync,
        )

    def get(self, key):
        return self._manager.get(key)

    def set(self, key, value):
        self._manager.set(key, value)

    def delete(self, key):
        self._manager.delete(key)

    def has(self, key):
        return self._manager.has(key)

    def size(self):
        return self._manager.size()

    def failover(self, shard_id):
        self._manager.failover(shard_id)

    def mark_shard_down(self, shard_id):
        self._manager.mark_shard_down(shard_id)

    def mark_shard_up(self, shard_id):
        self._manager.mark_shard_up(shard_id)

    def status(self):
        return self._manager.status()

    def close(self):
        self._manager.close()
