"""分片路由：key → shard 的确定性映射与故障隔离。

依赖：仅 errors 与标准库（store.py 依赖本模块），保证依赖图为无环：
    errors ← shard；errors ← replica；{shard, replica} ← store
"""

import threading
import zlib

from errors import InvalidKeyError, ShardDownError


def validate_key(key):
    """校验键合法性，非法时抛 InvalidKeyError。"""
    if not isinstance(key, str) or key == "":
        raise InvalidKeyError(f"key must be a non-empty string, got {key!r}")


class ShardManager:
    """把 key 确定性路由到 shard 引擎，并维护每个 shard 的 up/down 状态。

    路由函数：``zlib.crc32(key.encode("utf-8")) % shard_count``。
    选用 crc32 而非 Python 内置 ``hash()``：str 的 ``hash()`` 按进程随机
    （PYTHONHASHSEED），会导致重启后同一 key 落到不同 shard、journal 恢复
    路由不一致；crc32 跨进程稳定。
    """

    def __init__(self, shard_count, engine_factory):
        if not isinstance(shard_count, int) or shard_count < 1:
            raise ValueError(f"shard_count must be a positive integer, got {shard_count!r}")
        self._count = shard_count
        self._engines = [engine_factory(i) for i in range(shard_count)]
        self._up = [True] * shard_count
        self._lock = threading.RLock()

    def engine(self, index):
        with self._lock:
            self._check_index(index)
            return self._engines[index]

    def shard_of(self, key):
        validate_key(key)
        return zlib.crc32(key.encode("utf-8")) % self._count

    def _check_index(self, index):
        if not isinstance(index, int) or not (0 <= index < self._count):
            raise ValueError(f"shard index out of range [0, {self._count}): {index!r}")

    def _ensure_up(self, index):
        with self._lock:
            if not self._up[index]:
                raise ShardDownError(f"shard {index} is down")

    def get(self, key):
        index = self.shard_of(key)
        self._ensure_up(index)
        return self._engines[index].get(key)

    def set(self, key, value):
        index = self.shard_of(key)
        self._ensure_up(index)
        return self._engines[index].set(key, value)

    def delete(self, key):
        index = self.shard_of(key)
        self._ensure_up(index)
        return self._engines[index].delete(key)

    def mark_shard_down(self, index):
        with self._lock:
            self._check_index(index)
            self._up[index] = False

    def mark_shard_up(self, index):
        with self._lock:
            self._check_index(index)
            self._up[index] = True

    def status(self):
        with self._lock:
            result = []
            for i in range(self._count):
                entry = self._engines[i].status()
                entry["shard"] = i
                entry["state"] = "up" if self._up[i] else "down"
                result.append(entry)
            return result
