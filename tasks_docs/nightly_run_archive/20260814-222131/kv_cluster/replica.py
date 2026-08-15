"""主备复制：write-through 同步复制与 failover。

依赖：仅 errors 与标准库（不 import store），与 store.py 无循环依赖。
ReplicaManager 通过 KVStore 的内部协议协作：``_set_memory`` / ``_delete_memory`` /
``_restore`` / ``_journal_set`` / ``_journal_delete`` / ``_journal_path`` /
``items`` / ``set`` / ``delete`` / ``get`` / ``size`` / ``status`` / ``close``。
"""

import threading

from errors import ReplicationError

_MISSING = object()


class ReplicaManager:
    """primary + 1 backup 的复制单元（同步复制，写后读一致）。

    写序（保证 journal 只记录"已复制提交"）：
      1) 更新 primary 内存（校验失败则直接抛错，不动 backup）；
      2) write-through 到 backup（失败 -> 回滚 primary 内存并抛 ReplicationError）；
      3) 追加 primary journal（失败为罕见 IO 路径，尽力回滚两侧内存）。

    failover：backup 升级为 primary（数据原样保留），新 backup 由
    ``backup_factory`` 重建并回填 primary 当前全量数据。
    """

    def __init__(self, primary, backup, backup_factory=None, on_failover=None):
        if primary is backup:
            raise ValueError("primary and backup must be distinct stores")
        self._primary = primary
        self._backup = backup
        self._backup_factory = backup_factory
        self._on_failover = on_failover
        self._backup_healthy = True
        self._lock = threading.RLock()

    @property
    def primary(self):
        return self._primary

    @property
    def backup(self):
        return self._backup

    def get(self, key):
        with self._lock:
            return self._primary.get(key)

    def set(self, key, value):
        with self._lock:
            prev = self._primary._set_memory(key, value)
            try:
                self._backup.set(key, value)
            except Exception as exc:
                self._primary._restore(key, prev)
                self._backup_healthy = False
                raise ReplicationError(
                    f"backup write failed for key {key!r}; primary rolled back"
                ) from exc
            self._backup_healthy = True
            try:
                self._primary._journal_set(key, value)
            except Exception as exc:
                self._primary._restore(key, prev)
                self._backup._restore(key, prev)
                raise ReplicationError(
                    f"primary journal write failed for key {key!r}"
                ) from exc

    def delete(self, key):
        with self._lock:
            prev = self._primary._delete_memory(key)
            if prev is _MISSING:
                return False
            try:
                removed = self._backup.delete(key)
            except Exception as exc:
                self._primary._restore(key, prev)
                self._backup_healthy = False
                raise ReplicationError(
                    f"backup delete failed for key {key!r}; primary rolled back"
                ) from exc
            if not removed:
                self._primary._restore(key, prev)
                raise ReplicationError(
                    f"backup did not contain key {key!r}; primary rolled back"
                )
            self._backup_healthy = True
            try:
                self._primary._journal_delete(key)
            except Exception as exc:
                self._primary._restore(key, prev)
                self._backup._restore(key, prev)
                raise ReplicationError(
                    f"primary journal delete failed for key {key!r}"
                ) from exc
            return True

    def failover(self):
        """backup 升级为 primary，重建新 backup 并回填当前全量数据。

        回填保证新 backup 与 primary 数据完整一致（多次 failover 也不丢数据）；
        回填失败则保持原主备不变，抛 ReplicationError。

        顺序为「回填 -> 持久化角色(on_failover) -> 交换」：若中途崩溃，
        重启按已持久化角色恢复，而旧 backup（即将成为 primary）因 write-through
        已含全量数据，故任何时刻崩溃都不丢已提交写。
        """
        with self._lock:
            if self._backup_factory is None:
                raise ValueError("failover requires a backup_factory to rebuild the new backup")
            new_backup = self._backup_factory(self._backup._journal_path)
            try:
                for key, value in self._primary.items():
                    new_backup.set(key, value)
            except Exception as exc:
                raise ReplicationError(
                    "failed to backfill new backup after failover; old pair unchanged"
                ) from exc
            if self._on_failover is not None:
                self._on_failover(self._backup._journal_path, new_backup._journal_path)
            self._primary = self._backup
            self._backup = new_backup
            self._backup_healthy = True
            return self._primary

    def status(self):
        with self._lock:
            return {
                "type": "replicated",
                "primary_size": self._primary.size(),
                "backup_size": self._backup.size(),
                "primary_healthy": True,
                "backup_healthy": self._backup_healthy,
            }

    def close(self):
        with self._lock:
            self._primary.close()
            self._backup.close()
