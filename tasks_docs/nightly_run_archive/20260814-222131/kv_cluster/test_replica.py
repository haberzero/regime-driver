"""复制/分片：write-through、复制失败回滚、failover、路由与隔离、集群恢复。"""

import zlib

import pytest

from errors import (
    InvalidKeyError,
    KeyNotFoundError,
    ReplicationError,
    ShardDownError,
    StorageFullError,
)
from replica import ReplicaManager
from store import KVCluster, KVStore


class FaultyBackup(KVStore):
    """模拟 backup 写失败的注入点。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fault_on = False

    def set(self, key, value):
        if self.fault_on:
            raise OSError("backup unavailable (simulated)")
        return super().set(key, value)

    def delete(self, key):
        if self.fault_on:
            raise OSError("backup unavailable (simulated)")
        return super().delete(key)


def test_replication_write_through():
    primary = KVStore()
    backup = KVStore()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    rm.set("a", {"v": 1})
    assert primary.get("a") == {"v": 1}
    assert backup.get("a") == {"v": 1}
    rm.delete("a")
    assert not primary.has("a")
    assert not backup.has("a")
    rm.close()


def test_backup_failure_rollback_set():
    primary = KVStore()
    backup = FaultyBackup()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    rm.set("a", 1)
    backup.fault_on = True
    with pytest.raises(ReplicationError):
        rm.set("a", 2)
    assert rm.get("a") == 1
    assert primary.get("a") == 1
    assert rm.status()["backup_healthy"] is False
    rm.close()


def test_backup_failure_rollback_delete():
    primary = KVStore()
    backup = FaultyBackup()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    rm.set("a", 1)
    backup.fault_on = True
    with pytest.raises(ReplicationError):
        rm.delete("a")
    assert rm.get("a") == 1
    assert primary.get("a") == 1
    rm.close()


def test_cluster_usable_after_backup_failure():
    primary = KVStore()
    backup = FaultyBackup()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    rm.set("a", 1)
    backup.fault_on = True
    with pytest.raises(ReplicationError):
        rm.set("a", 2)
    backup.fault_on = False
    rm.set("a", 2)
    assert rm.get("a") == 2
    assert rm.status()["backup_healthy"] is True
    rm.close()


def test_replica_storage_full_propagates():
    primary = KVStore(max_size=1)
    backup = KVStore(max_size=1)
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore(max_size=1))
    rm.set("a", 1)
    with pytest.raises(StorageFullError):
        rm.set("b", 2)
    assert not backup.has("b")
    assert rm.get("a") == 1
    rm.close()


def test_failover_backup_data_intact():
    primary = KVStore()
    backup = KVStore()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    rm.set("x", 1)
    rm.set("y", {"n": 2})
    new_primary = rm.failover()
    assert new_primary is backup
    assert rm.get("x") == 1
    assert rm.get("y") == {"n": 2}
    assert rm.backup.size() == 2  # 新 backup 已回填全量数据
    rm.set("z", 3)
    assert rm.get("z") == 3
    assert rm.backup.get("z") == 3
    assert rm.backup.size() == 3
    rm.close()


def test_repeated_failover():
    primary = KVStore()
    backup = KVStore()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    for i in range(5):
        rm.set(f"k{i}", i)
    rm.failover()
    rm.set("extra", "e")
    rm.failover()
    for i in range(5):
        assert rm.get(f"k{i}") == i
    assert rm.get("extra") == "e"
    rm.close()


def test_failover_without_factory_raises():
    rm = ReplicaManager(KVStore(), KVStore())
    with pytest.raises(ValueError):
        rm.failover()
    rm.close()


def test_replica_invalid_key_propagates():
    primary = KVStore()
    backup = KVStore()
    rm = ReplicaManager(primary, backup, backup_factory=lambda _promoted: KVStore())
    with pytest.raises(InvalidKeyError):
        rm.set("", 1)
    rm.close()


def test_cluster_shard_routing_deterministic():
    c1 = KVCluster(shard_count=4, replication=True)
    c2 = KVCluster(shard_count=4, replication=True)
    for k in ("a", "hello", "世界", "x" * 50):
        assert c1._shards.shard_of(k) == zlib.crc32(k.encode("utf-8")) % 4
        assert c1._shards.shard_of(k) == c2._shards.shard_of(k)
    c1.set("hello", "world")
    assert c1.get("hello") == "world"
    c1.close()
    c2.close()


def test_cluster_shard_isolation():
    c = KVCluster(shard_count=4, replication=False)
    found = {}
    for k in (f"key{i}" for i in range(64)):
        sh = c._shards.shard_of(k)
        found.setdefault(sh, k)
        if len(found) == 4:
            break
    k0, k1 = found[0], found[1]
    c.set(k0, "v0")
    c.set(k1, "v1")
    c.mark_shard_down(0)
    with pytest.raises(ShardDownError):
        c.get(k0)
    with pytest.raises(ShardDownError):
        c.set(k0, "x")
    with pytest.raises(ShardDownError):
        c.delete(k0)
    assert c.get(k1) == "v1"
    c.set(k1, "v1b")
    assert c.get(k1) == "v1b"
    c.mark_shard_up(0)
    assert c.get(k0) == "v0"
    c.close()


def test_cluster_failover_keeps_data(tmp_path):
    c = KVCluster(shard_count=4, replication=True, data_dir=str(tmp_path / "d"))
    keys = {f"key-{i}": i for i in range(32)}
    for k, v in keys.items():
        c.set(k, v)
    for i in range(4):
        c.failover(i)
    for k, v in keys.items():
        assert c.get(k) == v
    c.set("after", 1)
    assert c.get("after") == 1
    c.close()


def test_cluster_failover_then_restart_preserves_writes(tmp_path):
    """回归：failover 后崩溃/重启，failover 前后的已提交写都必须可读。"""
    data_dir = str(tmp_path / "d")
    c1 = KVCluster(shard_count=2, replication=True, data_dir=data_dir)
    keys = {f"key-{i}": i for i in range(20)}
    for k, v in keys.items():
        c1.set(k, v)
    for i in range(2):
        c1.failover(i)
    post = {"post-0": "a", "post-1": "b"}
    for k, v in post.items():
        c1.set(k, v)
    c1.close()
    c2 = KVCluster(shard_count=2, replication=True, data_dir=data_dir)
    for k, v in keys.items():
        assert c2.get(k) == v
    for k, v in post.items():
        assert c2.get(k) == v
    c2.close()


def test_cluster_multiple_failovers_then_restart(tmp_path):
    data_dir = str(tmp_path / "d")
    c1 = KVCluster(shard_count=1, replication=True, data_dir=data_dir)
    c1.set("k0", 0)
    c1.failover(0)
    c1.set("k1", 1)
    c1.failover(0)
    c1.set("k2", 2)
    c1.close()
    c2 = KVCluster(shard_count=1, replication=True, data_dir=data_dir)
    assert c2.get("k0") == 0
    assert c2.get("k1") == 1
    assert c2.get("k2") == 2
    c2.close()


def test_cluster_journal_recovery_with_replication(tmp_path):
    data_dir = str(tmp_path / "data")
    c1 = KVCluster(shard_count=4, replication=True, data_dir=data_dir)
    for i in range(40):
        c1.set(f"key-{i}", {"i": i})
    c1.close()
    c2 = KVCluster(shard_count=4, replication=True, data_dir=data_dir)
    for i in range(40):
        assert c2.get(f"key-{i}") == {"i": i}
    c2.delete("key-0")
    c2.close()
    c3 = KVCluster(shard_count=4, replication=True, data_dir=data_dir)
    with pytest.raises(KeyNotFoundError):
        c3.get("key-0")
    assert c3.get("key-1") == {"i": 1}
    c3.close()


def test_cluster_status(tmp_path):
    c = KVCluster(shard_count=3, replication=True, data_dir=str(tmp_path / "d"))
    c.set("a", 1)
    st = c.status()
    assert len(st) == 3
    for entry in st:
        assert set(entry) == {
            "shard",
            "state",
            "type",
            "primary_size",
            "backup_size",
            "primary_healthy",
            "backup_healthy",
        }
        assert entry["state"] == "up"
        assert entry["type"] == "replicated"
    c.mark_shard_down(1)
    st = c.status()
    assert st[1]["state"] == "down"
    assert st[0]["state"] == "up"
    c.close()
    c2 = KVCluster(shard_count=2, replication=False)
    st2 = c2.status()
    assert st2[0]["type"] == "simple"
    assert "size" in st2[0]
    c2.close()


def test_failover_disabled_raises():
    c = KVCluster(shard_count=2, replication=False)
    with pytest.raises(ValueError):
        c.failover(0)
    c.close()


def test_invalid_args():
    with pytest.raises(ValueError):
        KVCluster(0)
    with pytest.raises(ValueError):
        KVCluster(-1)
    with pytest.raises(ValueError):
        KVCluster("4")
    c = KVCluster(shard_count=2)
    with pytest.raises(ValueError):
        c.failover(2)
    with pytest.raises(ValueError):
        c.mark_shard_down(2)
    with pytest.raises(ValueError):
        c.mark_shard_up(-1)
    c.close()
