"""单节点 KVStore 与集群门面 KVCluster。

依赖无环：errors ← shard ← store；errors ← replica ← store。
"""

import json
import os
import threading

from errors import KeyNotFoundError, KVClusterError, StorageFullError
from replica import ReplicaManager
from shard import ShardManager, validate_key

_MISSING = object()


def _check_json_value(value):
    """value 必须可 JSON 序列化（journal 存储要求）。"""
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value must be JSON-serializable, got {value!r}") from exc


class KVStore:
    """线程安全的内存 KVStore，可选 append-only journal 持久化。

    journal 为每行一个 JSON 记录的追加日志（``{"op": "set|delete", ...}``）；
    启动时重放恢复已提交写入，写入中途崩溃产生的尾部残缺记录被丢弃。
    delete 缺失键为幂等 no-op（返回 False）。
    """

    def __init__(self, journal_path=None, max_size=None, fsync=True):
        if max_size is not None and (not isinstance(max_size, int) or max_size < 1):
            raise ValueError(f"max_size must be a positive integer or None, got {max_size!r}")
        self._journal_path = journal_path
        self._max_size = max_size
        self._fsync = bool(fsync)
        self._data = {}
        self._lock = threading.RLock()
        self._journal = None
        self._closed = False
        if journal_path is not None:
            parent = os.path.dirname(journal_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._journal = open(journal_path, "a", encoding="utf-8")
            self._recover()

    # ---- 公开读写接口 ----

    def set(self, key, value):
        with self._lock:
            self._ensure_open()
            prev = self._set_memory(key, value)
            try:
                self._journal_set(key, value)
            except Exception:
                self._restore(key, prev)
                raise

    def get(self, key):
        with self._lock:
            self._ensure_open()
            validate_key(key)
            try:
                return self._data[key]
            except KeyError:
                raise KeyNotFoundError(f"key not found: {key!r}") from None

    def delete(self, key):
        """删除 key；不存在时幂等返回 False。"""
        with self._lock:
            self._ensure_open()
            prev = self._delete_memory(key)
            if prev is _MISSING:
                return False
            try:
                self._journal_delete(key)
            except Exception:
                self._restore(key, prev)
                raise
            return True

    def has(self, key):
        with self._lock:
            self._ensure_open()
            validate_key(key)
            return key in self._data

    def size(self):
        with self._lock:
            return len(self._data)

    def keys(self):
        with self._lock:
            return set(self._data.keys())

    def items(self):
        """当前全部 (key, value) 对的快照列表。"""
        with self._lock:
            return list(self._data.items())

    def close(self):
        with self._lock:
            self._closed = True
            if self._journal is not None:
                self._journal.close()
                self._journal = None

    # ---- 复制协议（供 ReplicaManager 使用，勿直接调用） ----

    def _set_memory(self, key, value):
        with self._lock:
            self._ensure_open()
            validate_key(key)
            _check_json_value(value)
            if key not in self._data and self._max_size is not None and len(self._data) >= self._max_size:
                raise StorageFullError(f"storage full: max_size={self._max_size}")
            prev = self._data.get(key, _MISSING)
            self._data[key] = value
            return prev

    def _delete_memory(self, key):
        with self._lock:
            self._ensure_open()
            validate_key(key)
            return self._data.pop(key, _MISSING)

    def _restore(self, key, prev):
        with self._lock:
            if prev is _MISSING:
                self._data.pop(key, None)
            else:
                self._data[key] = prev

    def _journal_set(self, key, value):
        with self._lock:
            self._append("set", key, value)

    def _journal_delete(self, key):
        with self._lock:
            self._append("delete", key, None)

    def status(self):
        return {"type": "simple", "size": self.size()}

    # ---- 内部工具 ----

    def _ensure_open(self):
        if self._closed:
            raise ValueError("store is closed")

    def _append(self, op, key, value):
        if self._journal is None:
            return
        line = json.dumps({"op": op, "key": key, "value": value}, ensure_ascii=False) + "\n"
        self._journal.write(line)
        self._journal.flush()
        if self._fsync:
            os.fsync(self._journal.fileno())

    def _recover(self):
        with self._lock:
            try:
                with open(self._journal_path, "r", encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except FileNotFoundError:
                return
            last = len(lines) - 1
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    if i == last:
                        break  # 写入中途崩溃留下的尾部残缺记录，丢弃
                    raise KVClusterError(
                        f"corrupt journal {self._journal_path!r} at line {i + 1}"
                    ) from None
                self._apply_record(rec)

    def _apply_record(self, rec):
        op = rec.get("op")
        key = rec.get("key")
        if not isinstance(key, str):
            raise KVClusterError(f"corrupt journal record: missing key: {rec!r}")
        if op == "set":
            self._data[key] = rec.get("value")
        elif op == "delete":
            self._data.pop(key, None)
        else:
            raise KVClusterError(f"corrupt journal record: unknown op {op!r}")


class KVCluster:
    """KV 集群门面：ShardManager（路由/隔离） + ReplicaManager（主备复制）。

    构造参数：
        shard_count    分片数（>=1）。
        replication    True 时每 shard 为 primary+backup 复制单元，否则为单 KVStore。
        data_dir       journal 目录；None 时纯内存（不落盘，适合并发/内存测试）。
        max_size       每存储键数上限；None 时不限。
        fsync          journal 追加后是否 fsync（崩溃恢复保证）。
    """

    def __init__(self, shard_count, replication=True, data_dir=None, max_size=None, fsync=True):
        if not isinstance(shard_count, int) or shard_count < 1:
            raise ValueError(f"shard_count must be a positive integer, got {shard_count!r}")
        self._shard_count = shard_count
        self._replication = bool(replication)
        self._data_dir = data_dir
        self._max_size = max_size
        self._fsync = bool(fsync)
        if data_dir is not None:
            os.makedirs(data_dir, exist_ok=True)
        self._shards = ShardManager(shard_count, self._make_engine)

    def _journal_path(self, shard, role):
        if self._data_dir is None:
            return None
        return os.path.join(self._data_dir, f"shard{shard}_{role}.journal")

    def _role_marker_path(self, shard):
        return os.path.join(self._data_dir, f"shard{shard}.role")

    def _read_role(self, shard):
        """读取持久化的主备角色；无标记时返回初始角色 p/b。"""
        path = self._role_marker_path(shard)
        default = {"primary": f"shard{shard}_p.journal", "backup": f"shard{shard}_b.journal"}
        if not os.path.exists(path):
            return default
        try:
            with open(path, encoding="utf-8") as fh:
                role = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise KVClusterError(f"corrupt role file {path!r}") from exc
        if not isinstance(role, dict) or "primary" not in role or "backup" not in role:
            raise KVClusterError(f"corrupt role file {path!r}")
        return role

    def _write_role(self, shard, role):
        """原子写角色标记（临时文件 + fsync + rename）。"""
        path = self._role_marker_path(shard)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(role, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _make_engine(self, shard):
        if self._replication:
            if self._data_dir is None:
                primary = KVStore(None, max_size=self._max_size, fsync=self._fsync)
                backup = KVStore(None, max_size=self._max_size, fsync=self._fsync)
            else:
                role = self._read_role(shard)
                if not os.path.exists(self._role_marker_path(shard)):
                    self._write_role(shard, role)
                primary = KVStore(
                    os.path.join(self._data_dir, role["primary"]),
                    max_size=self._max_size,
                    fsync=self._fsync,
                )
                backup = KVStore(
                    os.path.join(self._data_dir, role["backup"]),
                    max_size=self._max_size,
                    fsync=self._fsync,
                )
            return ReplicaManager(
                primary,
                backup,
                backup_factory=self._build_backup_factory(shard),
                on_failover=self._build_on_failover(shard),
            )
        return KVStore(
            self._journal_path(shard, "s"), max_size=self._max_size, fsync=self._fsync
        )

    def _build_backup_factory(self, shard):
        def factory(promoted_journal_path):
            if self._data_dir is None:
                return KVStore(None, max_size=self._max_size, fsync=self._fsync)
            prefix = f"shard{shard}_b"
            base = os.path.basename(promoted_journal_path)
            rest = base[len(prefix):-len(".journal")]
            n = (int(rest) if rest else 0) + 1
            path = os.path.join(self._data_dir, f"{prefix}{n}.journal")
            if os.path.exists(path):
                os.remove(path)  # 上次 failover 中途崩溃留下的孤儿文件，保证新 backup 为空
            return KVStore(path, max_size=self._max_size, fsync=self._fsync)

        return factory

    def _build_on_failover(self, shard):
        def on_failover(promoted_journal_path, new_backup_journal_path):
            if self._data_dir is None:
                return
            role = self._read_role(shard)
            role["primary"] = os.path.basename(promoted_journal_path)
            role["backup"] = os.path.basename(new_backup_journal_path)
            self._write_role(shard, role)

        return on_failover

    def get(self, key):
        return self._shards.get(key)

    def set(self, key, value):
        return self._shards.set(key, value)

    def delete(self, key):
        return self._shards.delete(key)

    def failover(self, shard_index):
        if not self._replication:
            raise ValueError("replication disabled: failover unavailable")
        return self._shards.engine(shard_index).failover()

    def mark_shard_down(self, shard_index):
        self._shards.mark_shard_down(shard_index)

    def mark_shard_up(self, shard_index):
        self._shards.mark_shard_up(shard_index)

    def status(self):
        return self._shards.status()

    def close(self):
        for i in range(self._shard_count):
            self._shards.engine(i).close()
