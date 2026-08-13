import threading
import zlib

import pytest

from errors import InvalidKeyError, KeyNotFoundError, ShardDownError, StorageFullError
from store import KVCluster, KVStore


def test_basic_operations():
    s = KVStore()
    s.set("a", 1)
    s.set("b", {"x": [1, 2, 3]})
    assert s.get("a") == 1
    assert s.get("b") == {"x": [1, 2, 3]}
    assert s.has("a")
    assert s.size() == 2
    assert set(s.keys()) == {"a", "b"}
    s.set("a", 99)
    assert s.get("a") == 99
    assert s.size() == 2
    s.delete("a")
    assert not s.has("a")
    with pytest.raises(KeyNotFoundError):
        s.get("a")


def test_complex_json_values(tmp_path):
    payload = {"nested": [1, "two", {"three": 3.5}], "flag": True, "nil": None}
    s = KVStore(journal_path=tmp_path / "j.journal")
    s.set("k", payload)
    s2 = KVStore(journal_path=tmp_path / "j.journal")
    assert s2.get("k") == payload


def test_journal_recovery(tmp_path):
    p = tmp_path / "store.journal"
    s1 = KVStore(journal_path=p)
    s1.set("a", 1)
    s1.set("b", 2)
    s1.set("c", 3)
    s1.delete("b")
    s2 = KVStore(journal_path=p)
    assert s2.get("a") == 1
    assert s2.get("c") == 3
    assert not s2.has("b")
    assert s2.size() == 2
    s2.set("d", 4)
    s3 = KVStore(journal_path=p)
    assert s3.size() == 3
    assert s3.get("d") == 4


def test_storage_limit():
    s = KVStore(limit=3)
    s.set("a", 1)
    s.set("b", 2)
    s.set("c", 3)
    with pytest.raises(StorageFullError):
        s.set("d", 4)
    s.set("a", 10)
    assert s.get("a") == 10
    s.delete("b")
    s.set("d", 4)
    assert s.get("d") == 4
    assert s.size() == 3


def test_invalid_key():
    s = KVStore()
    with pytest.raises(InvalidKeyError):
        s.set("", 1)
    with pytest.raises(InvalidKeyError):
        s.get(None)
    with pytest.raises(InvalidKeyError):
        s.set(123, 1)
    with pytest.raises(InvalidKeyError):
        s.delete("")


def test_non_serializable_value():
    s = KVStore()
    with pytest.raises(ValueError):
        s.set("k", object())
    assert not s.has("k")


def test_negative_limit():
    with pytest.raises(ValueError):
        KVStore(limit=-1)


def test_key_not_found():
    s = KVStore()
    with pytest.raises(KeyNotFoundError):
        s.get("missing")
    with pytest.raises(KeyNotFoundError):
        s.delete("missing")


def test_shard_routing_and_isolation():
    cluster = KVCluster(shard_count=4, replication=True)
    keys = [f"key-{i}" for i in range(120)]
    for k in keys:
        cluster.set(k, k)

    def shard_of(k):
        return zlib.crc32(k.encode("utf-8")) % 4

    shard_keys = {}
    for k in keys:
        shard_keys.setdefault(shard_of(k), []).append(k)

    for i in range(4):
        assert cluster.status()[i]["primary_size"] == len(shard_keys.get(i, []))

    target_shard = 2
    cluster.mark_shard_down(target_shard)
    for k in shard_keys[target_shard]:
        with pytest.raises(ShardDownError):
            cluster.get(k)
    for k in shard_keys[target_shard]:
        with pytest.raises(ShardDownError):
            cluster.set(k, "x")
    for i in range(4):
        if i != target_shard:
            for k in shard_keys[i]:
                assert cluster.get(k) == k

    st = cluster.status()
    assert st[target_shard]["state"] == "down"
    assert all(st[i]["state"] == "up" for i in range(4) if i != target_shard)

    cluster.mark_shard_up(target_shard)
    for k in shard_keys[target_shard]:
        assert cluster.get(k) == k


def test_plain_mode_fault_isolation():
    cluster = KVCluster(shard_count=2, replication=False)
    for i in range(40):
        cluster.set(f"k{i}", i)
    assert cluster.size() == 40
    st = cluster.status()
    assert all(d["replicated"] is False for d in st)
    target = next(
        f"k{i}" for i in range(200) if zlib.crc32(f"k{i}".encode("utf-8")) % 2 == 1
    )
    cluster.mark_shard_down(1)
    with pytest.raises(ShardDownError):
        cluster.get(target)
    cluster.mark_shard_up(1)
    assert cluster.get(target) == int(target[1:])


def test_cluster_status():
    cluster = KVCluster(shard_count=3, replication=True)
    cluster.set("alpha", 1)
    st = cluster.status()
    assert len(st) == 3
    assert all(
        "backup_size" in d and "backup_healthy" in d and "primary_size" in d for d in st
    )
    assert sum(d["primary_size"] for d in st) == 1
    assert all(d["backup_healthy"] for d in st)


def test_concurrent_operations():
    cluster = KVCluster(shard_count=3, replication=True)
    nthreads = 8
    per = 40
    barrier = threading.Barrier(nthreads)
    errors = []

    def worker(tid):
        try:
            barrier.wait()
            for j in range(per):
                k = f"t{tid}-{j}"
                cluster.set(k, j)
                assert cluster.get(k) == j
                if j % 4 == 0 and j > 0:
                    cluster.delete(f"t{tid}-{j - 1}")
        except Exception as exc:
            errors.append((tid, exc))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(nthreads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors

    deleted = {j - 1 for j in range(per) if j % 4 == 0 and j > 0}
    total = per - len(deleted)
    assert cluster.size() == total * nthreads
    for t in range(nthreads):
        for j in range(per):
            if j in deleted:
                continue
            assert cluster.get(f"t{t}-{j}") == j
