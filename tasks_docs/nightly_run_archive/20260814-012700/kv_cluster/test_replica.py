import threading
import zlib

import pytest

from errors import InvalidKeyError, KeyNotFoundError, ReplicationError, StorageFullError
from replica import ReplicaManager
from store import KVCluster


def test_failover_keeps_data():
    rm = ReplicaManager(shard_id=0)
    for i in range(50):
        rm.set(f"k{i}", {"v": i, "tags": [i, i + 1]})
    assert rm.backup_size() == 50
    assert rm.backup_healthy()

    rm.failover()
    assert rm.primary.size() == 50
    for i in range(50):
        assert rm.get(f"k{i}") == {"v": i, "tags": [i, i + 1]}
    assert rm.backup_size() == 50
    assert rm.backup_healthy()

    rm.set("new", 1)
    assert rm.get("new") == 1
    assert rm.backup_size() == 51

    rm.failover()
    assert rm.get("new") == 1
    assert rm.primary.size() == 51
    assert rm.backup_size() == 51


def test_replication_failure_rolls_back_new_key():
    rm = ReplicaManager(shard_id=0, limit=None, backup_limit=3)
    for i in range(3):
        rm.set(f"k{i}", i)
    assert rm.backup_size() == 3

    with pytest.raises(ReplicationError):
        rm.set("k3", 3)

    assert not rm.primary.has("k3")
    with pytest.raises(KeyNotFoundError):
        rm.get("k3")
    assert rm.primary.size() == 3
    assert rm.backup_size() == 3

    rm.set("k0", 100)
    assert rm.get("k0") == 100
    assert rm.backup.get("k0") == 100

    rm.delete("k1")
    rm.set("k4", 4)
    assert rm.get("k4") == 4
    assert rm.backup_size() == 3


def test_replication_failure_restores_old_value(monkeypatch):
    rm = ReplicaManager(shard_id=0)
    rm.set("x", "old")

    def boom(*args, **kwargs):
        raise OSError("backup down")

    monkeypatch.setattr(rm.backup, "set", boom)
    with pytest.raises(ReplicationError):
        rm.set("x", "new")

    assert rm.get("x") == "old"
    assert rm.primary.size() == 1


def test_replication_failure_delete_rolls_back(monkeypatch):
    rm = ReplicaManager(shard_id=0)
    rm.set("x", "old")

    def boom(*args, **kwargs):
        raise OSError("backup down")

    monkeypatch.setattr(rm.backup, "delete", boom)
    with pytest.raises(ReplicationError):
        rm.delete("x")

    assert rm.get("x") == "old"


def test_cluster_replication_error():
    cluster = KVCluster(shard_count=1, replication=True, limit=None, backup_limit=2)
    cluster.set("a", 1)
    cluster.set("b", 2)
    with pytest.raises(ReplicationError):
        cluster.set("c", 3)
    assert not cluster.has("c")
    assert cluster.get("a") == 1
    cluster.delete("a")
    cluster.set("c", 3)
    assert cluster.get("c") == 3
    assert cluster.size() == 2


def test_cluster_failover_via_facade():
    cluster = KVCluster(shard_count=2, replication=True)
    for i in range(100):
        cluster.set(f"k{i}", i)
    target = zlib.crc32(b"k0") % 2
    cluster.failover(target)
    assert cluster.get("k0") == 0
    st = cluster.status()
    assert st[target]["primary_size"] == st[target]["backup_size"]
    assert all(d["backup_healthy"] for d in st)


def test_replica_exceptions():
    rm = ReplicaManager(shard_id=0)
    with pytest.raises(KeyNotFoundError):
        rm.get("nope")
    with pytest.raises(InvalidKeyError):
        rm.set("", 1)
    rm2 = ReplicaManager(shard_id=1, limit=1)
    rm2.set("a", 1)
    with pytest.raises(StorageFullError):
        rm2.set("b", 2)


def test_concurrent_replicated_writes():
    cluster = KVCluster(shard_count=2, replication=True)
    nthreads = 4
    per = 25
    barrier = threading.Barrier(nthreads)
    errors = []

    def worker(tid):
        try:
            barrier.wait()
            for j in range(per):
                k = f"r{tid}-{j}"
                cluster.set(k, (tid, j))
                assert cluster.get(k) == (tid, j)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(nthreads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    assert cluster.size() == nthreads * per
    for t in range(nthreads):
        for j in range(per):
            assert cluster.get(f"r{t}-{j}") == (t, j)


def test_cluster_journal_recovery(tmp_path):
    jd = tmp_path / "journals"
    c1 = KVCluster(shard_count=2, replication=True, journal_dir=jd)
    for i in range(30):
        c1.set(f"k{i}", i)
    c2 = KVCluster(shard_count=2, replication=True, journal_dir=jd)
    for i in range(30):
        assert c2.get(f"k{i}") == i
    assert c2.size() == 30


def test_failover_with_journal_recovery(tmp_path):
    jd = tmp_path / "journals"
    c1 = KVCluster(shard_count=1, replication=True, journal_dir=jd)
    for i in range(20):
        c1.set(f"k{i}", i)
    c1.failover(0)
    c1.set("after", "x")
    c2 = KVCluster(shard_count=1, replication=True, journal_dir=jd)
    assert c2.get("after") == "x"
    assert c2.size() == 21
