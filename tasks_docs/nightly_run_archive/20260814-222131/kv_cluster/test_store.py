"""KVStore 单节点：基础语义、journal 恢复、并发一致性、异常、存储上限。"""

import json
import threading

import pytest

from errors import (
    InvalidKeyError,
    KeyNotFoundError,
    KVClusterError,
    ReplicationError,
    ShardDownError,
    StorageFullError,
)
from store import KVCluster, KVStore


def test_set_get_roundtrip():
    s = KVStore()
    value = {"name": "x", "nums": [1, 2, 3], "flag": True, "nil": None}
    s.set("k", value)
    assert s.get("k") == value


def test_get_missing_raises():
    s = KVStore()
    with pytest.raises(KeyNotFoundError):
        s.get("missing")


def test_delete_semantics():
    s = KVStore()
    s.set("a", 1)
    assert s.delete("a") is True
    assert not s.has("a")
    assert s.delete("a") is False


def test_has_size_keys():
    s = KVStore()
    s.set("a", 1)
    s.set("b", 2)
    assert s.has("a") and s.has("b") and not s.has("c")
    assert s.size() == 2
    assert s.keys() == {"a", "b"}


def test_invalid_key_raises():
    s = KVStore()
    s.set("ok", 1)
    for bad in ("", None, 123, 1.5, b"bytes"):
        with pytest.raises(InvalidKeyError):
            s.set(bad, 1)
        with pytest.raises(InvalidKeyError):
            s.get(bad)
        with pytest.raises(InvalidKeyError):
            s.delete(bad)
        with pytest.raises(InvalidKeyError):
            s.has(bad)


def test_non_json_value_raises():
    s = KVStore()
    with pytest.raises(ValueError):
        s.set("k", object())
    assert not s.has("k")


def test_storage_full():
    s = KVStore(max_size=2)
    s.set("a", 1)
    s.set("b", 2)
    with pytest.raises(StorageFullError):
        s.set("c", 3)
    assert s.size() == 2
    assert not s.has("c")
    s.set("a", 99)
    assert s.get("a") == 99
    assert s.size() == 2


def test_delete_absent_not_journaled(tmp_path):
    jf = tmp_path / "j.log"
    s = KVStore(journal_path=str(jf))
    s.set("a", 1)
    assert s.delete("missing") is False
    s.close()
    with open(jf, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 1


def test_journal_recovery(tmp_path):
    jf = tmp_path / "j.log"
    s = KVStore(journal_path=str(jf))
    values = {f"k{i}": {"i": i, "list": [i, i + 1], "b": True, "n": None} for i in range(20)}
    for k, v in values.items():
        s.set(k, v)
    s.close()
    s2 = KVStore(journal_path=str(jf))
    assert s2.size() == 20
    for k, v in values.items():
        assert s2.get(k) == v


def test_journal_recovery_after_delete(tmp_path):
    jf = tmp_path / "j.log"
    s = KVStore(journal_path=str(jf))
    s.set("a", 1)
    s.set("b", 2)
    s.delete("a")
    s.close()
    s2 = KVStore(journal_path=str(jf))
    with pytest.raises(KeyNotFoundError):
        s2.get("a")
    assert s2.get("b") == 2


def test_journal_ignores_torn_tail(tmp_path):
    jf = tmp_path / "j.log"
    s = KVStore(journal_path=str(jf))
    s.set("a", 1)
    s.set("b", 2)
    s.close()
    with open(jf, "a", encoding="utf-8") as fh:
        fh.write('{"op": "set", "key": "c", "value": ')  # 写入中途崩溃的残缺尾记录
    s2 = KVStore(journal_path=str(jf))
    assert s2.get("a") == 1
    assert s2.get("b") == 2
    assert not s2.has("c")


def test_journal_midfile_corruption_raises(tmp_path):
    jf = tmp_path / "j.log"
    with open(jf, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": "set", "key": "x", "value": 1}) + "\n")
        fh.write("this is not json\n")
        fh.write(json.dumps({"op": "set", "key": "y", "value": 2}) + "\n")
    with pytest.raises(KVClusterError):
        KVStore(journal_path=str(jf))


def test_concurrent_no_lost_writes():
    cluster = KVCluster(shard_count=4)
    threads = 8
    iters = 300
    barrier = threading.Barrier(threads)
    errors = []

    def worker(tid):
        key = f"thread-{tid}"
        try:
            barrier.wait()
            for i in range(iters):
                cluster.set(key, {"tid": tid, "i": i})
        except Exception as exc:  # noqa: BLE001 - 收集以便统一断言
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    for t in range(threads):
        assert cluster.get(f"thread-{t}") == {"tid": t, "i": iters - 1}


def test_concurrent_mixed_ops_no_exception_leak():
    cluster = KVCluster(shard_count=4)
    perm = [f"perm-{i}" for i in range(32)]
    for i, k in enumerate(perm):
        cluster.set(k, i)
    threads = 8
    iters = 300
    barrier = threading.Barrier(threads)
    errors = []

    def worker(tid):
        try:
            barrier.wait()
            for it in range(iters):
                k = perm[(tid + it) % len(perm)]
                assert cluster.get(k) == (tid + it) % len(perm)
                cluster.set(f"shared-{it % 8}", it)
                mine = f"mine-{tid}-{it}"
                cluster.set(mine, it)
                cluster.delete(mine)
        except Exception as exc:  # noqa: BLE001 - 收集以便统一断言
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    for i, k in enumerate(perm):
        assert cluster.get(k) == i
    for sh in range(8):
        assert isinstance(cluster.get(f"shared-{sh}"), int)


def test_exception_hierarchy():
    for exc in (
        KeyNotFoundError,
        ShardDownError,
        ReplicationError,
        InvalidKeyError,
        StorageFullError,
    ):
        assert issubclass(exc, KVClusterError)
