import threading

import pytest

from errors import (
    InvalidKeyError,
    KeyNotFoundError,
    ReplicationError,
    ShardDownError,
    StorageFullError,
)
from replica import ReplicaManager
from shard import ShardManager
from store import KVCluster, KVStore


def make_manager():
    return ReplicaManager(KVStore(), KVStore(), backup_factory=KVStore)


class TestReplicaManager:
    def test_set_replicates_to_backup(self):
        manager = make_manager()
        manager.set("a", 1)
        assert manager.primary.get("a") == 1
        assert manager.backup.get("a") == 1

    def test_get_reads_primary(self):
        manager = make_manager()
        manager.set("a", 1)
        assert manager.get("a") == 1

    def test_delete_replicates(self):
        manager = make_manager()
        manager.set("a", 1)
        manager.delete("a")
        assert not manager.primary.has("a")
        assert not manager.backup.has("a")

    def test_delete_missing_raises(self):
        manager = make_manager()
        with pytest.raises(KeyNotFoundError):
            manager.delete("nope")

    def test_primary_write_validation_before_backup(self):
        manager = make_manager()
        with pytest.raises(InvalidKeyError):
            manager.set(None, 1)

    def test_size_reflects_primary(self):
        manager = make_manager()
        manager.set("a", 1)
        manager.set("b", 2)
        assert manager.size == 2

    def test_replication_failure_rolls_back_insert(self, monkeypatch):
        manager = make_manager()

        def failing_set(key, value):
            raise OSError("backup disk failure")

        with pytest.raises(ReplicationError):
            with monkeypatch.context() as context:
                context.setattr(manager.backup, "set", failing_set)
                manager.set("new", 1)

        assert not manager.primary.has("new")
        assert not manager.backup.has("new")
        manager.set("new", 1)
        assert manager.get("new") == 1

    def test_replication_failure_rolls_back_overwrite(self, monkeypatch):
        manager = make_manager()
        manager.set("k", "old")

        def failing_set(key, value):
            raise OSError("backup disk failure")

        with pytest.raises(ReplicationError):
            with monkeypatch.context() as context:
                context.setattr(manager.backup, "set", failing_set)
                manager.set("k", "new")

        assert manager.primary.get("k") == "old"
        assert manager.backup.get("k") == "old"
        assert manager.get("k") == "old"

    def test_delete_failure_rolls_back(self, monkeypatch):
        manager = make_manager()
        manager.set("k", "v")

        def failing_delete(key):
            raise OSError("backup disk failure")

        with pytest.raises(ReplicationError):
            with monkeypatch.context() as context:
                context.setattr(manager.backup, "delete", failing_delete)
                manager.delete("k")

        assert manager.primary.get("k") == "v"
        assert manager.backup.get("k") == "v"

    def test_failover_promotes_backup_with_full_data(self):
        manager = make_manager()
        manager.set("a", 1)
        manager.set("b", {"x": [1, 2, 3]})
        manager.set("c", "three")

        old_primary = manager.primary
        old_backup = manager.backup
        manager.failover()

        assert manager.primary is old_backup
        assert manager.primary is not old_primary
        assert manager.backup is not old_backup
        assert manager.primary.get("a") == 1
        assert manager.primary.get("b") == {"x": [1, 2, 3]}
        assert manager.primary.get("c") == "three"
        assert manager.backup.get("a") == 1
        assert manager.backup.get("b") == {"x": [1, 2, 3]}
        assert manager.backup.get("c") == "three"
        assert manager.backup_healthy()

    def test_continue_after_failover(self):
        manager = make_manager()
        manager.set("a", 1)
        manager.failover()
        manager.set("b", 2)
        assert manager.primary.get("a") == 1
        assert manager.primary.get("b") == 2
        assert manager.backup.get("b") == 2

    def test_backup_healthy_detects_divergence(self):
        manager = make_manager()
        manager.set("a", 1)
        assert manager.backup_healthy()
        manager.primary.set("extra", 1)
        assert not manager.backup_healthy()


class TestKVCluster:
    def test_basic_roundtrip(self):
        cluster = KVCluster(3)
        cluster.set("name", "alice")
        assert cluster.get("name") == "alice"
        assert cluster.has("name")
        cluster.delete("name")
        assert not cluster.has("name")

    def test_status_replication(self):
        cluster = KVCluster(3, replication=True)
        cluster.set("a", 1)
        cluster.set("b", 2)
        status = cluster.status()
        assert status["shard_count"] == 3
        assert status["replication"] is True
        assert len(status["shards"]) == 3
        total = 0
        for info in status["shards"].values():
            assert info["down"] is False
            assert info["replication"] is True
            assert info["primary_size"] == info["backup_size"] == info["size"]
            assert info["backup_healthy"] is True
            total += info["size"]
        assert total == 2

    def test_status_detects_unhealthy_backup(self):
        cluster = KVCluster(2, replication=True)
        cluster.set("a", 1)
        shard_id = ShardManager.shard_id_for("a", 2)
        cluster._shards.get_store(shard_id).primary.set("rogue", 1)
        status = cluster.status()
        assert status["shards"][shard_id]["backup_healthy"] is False

    def test_cluster_failover_preserves_data(self):
        cluster = KVCluster(3, replication=True)
        for i in range(20):
            cluster.set("key%d" % i, i)
        shard_id = ShardManager.shard_id_for("key0", 3)
        manager = cluster._shards.get_store(shard_id)
        old_primary = manager.primary

        cluster.failover(shard_id)

        assert manager.primary is not old_primary
        for i in range(20):
            if ShardManager.shard_id_for("key%d" % i, 3) == shard_id:
                assert cluster.get("key%d" % i) == i
        status = cluster.status()
        assert status["shards"][shard_id]["backup_healthy"] is True
        cluster.set("newkey", 99)
        assert cluster.get("newkey") == 99

    def test_failover_requires_replication(self):
        cluster = KVCluster(2, replication=False)
        with pytest.raises(ValueError):
            cluster.failover(0)

    def test_cluster_shard_isolation(self):
        cluster = KVCluster(4, replication=True)
        target = next(
            "t%d" % i
            for i in range(2000)
            if ShardManager.shard_id_for("t%d" % i, 4) == 0
        )
        other = next(
            "o%d" % i
            for i in range(2000)
            if ShardManager.shard_id_for("o%d" % i, 4) != 0
        )
        cluster.set(target, 1)
        cluster.set(other, 2)
        cluster.mark_shard_down(0)
        with pytest.raises(ShardDownError):
            cluster.get(target)
        assert cluster.get(other) == 2
        cluster.set(other, 3)
        assert cluster.get(other) == 3
        cluster.mark_shard_up(0)
        assert cluster.get(target) == 1

    def test_cluster_storage_full(self):
        cluster = KVCluster(2, replication=True, max_size=3)
        shard = ShardManager.shard_id_for("anchor", 2)
        keys = []
        i = 0
        while len(keys) < 4:
            key = "cap%d" % i
            if ShardManager.shard_id_for(key, 2) == shard:
                keys.append(key)
            i += 1
        for key in keys[:3]:
            cluster.set(key, 1)
        with pytest.raises(StorageFullError):
            cluster.set(keys[3], 2)
        cluster.set(keys[0], 100)
        assert cluster.get(keys[0]) == 100
        assert not cluster.has(keys[3])

    def test_cluster_replication_failure_rollback(self, monkeypatch):
        cluster = KVCluster(2, replication=True)
        cluster.set("keep", "v")
        key = next(
            "rk%d" % i
            for i in range(2000)
            if ShardManager.shard_id_for("rk%d" % i, 2) == 0
        )
        shard_id = ShardManager.shard_id_for(key, 2)
        backup = cluster._shards.get_store(shard_id).backup

        def failing_set(k, value):
            raise OSError("backup disk failure")

        with pytest.raises(ReplicationError):
            with monkeypatch.context() as context:
                context.setattr(backup, "set", failing_set)
                cluster.set(key, 1)

        assert not cluster.has(key)
        assert cluster.get("keep") == "v"
        cluster.set(key, 2)
        assert cluster.get(key) == 2

    def test_cluster_recovery_after_crash(self, tmp_path):
        journal_dir = str(tmp_path / "journals")
        c1 = KVCluster(3, replication=True, journal_dir=journal_dir)
        for i in range(40):
            c1.set("key%d" % i, i)

        c2 = KVCluster(3, replication=True, journal_dir=journal_dir)
        assert c2.status()["shard_count"] == 3
        for i in range(40):
            assert c2.get("key%d" % i) == i
        c1.close()
        c2.close()

    def test_cluster_recovery_preserves_failover(self, tmp_path):
        journal_dir = str(tmp_path / "journals")
        c1 = KVCluster(3, replication=True, journal_dir=journal_dir)
        for i in range(10):
            c1.set("key%d" % i, i)
        shard_id = ShardManager.shard_id_for("key0", 3)
        c1.failover(shard_id)
        c1.set("post_failover", 99)

        c2 = KVCluster(3, replication=True, journal_dir=journal_dir)
        assert c2.get("post_failover") == 99
        for i in range(10):
            assert c2.get("key%d" % i) == i
        for info in c2.status()["shards"].values():
            assert info["backup_healthy"] is True
        c1.close()
        c2.close()

    def test_8_threads_concurrent_cluster(self):
        cluster = KVCluster(4, replication=True)
        n_threads = 8
        per_thread = 80
        barrier = threading.Barrier(n_threads)
        failures = []
        failures_lock = threading.Lock()

        def worker(thread_id):
            try:
                barrier.wait()
                base = thread_id * per_thread
                for i in range(per_thread):
                    cluster.set("k%d" % (base + i), i)
                for i in range(per_thread):
                    assert cluster.get("k%d" % (base + i)) == i
                for i in range(0, per_thread, 3):
                    cluster.delete("k%d" % (base + i))
            except Exception as exc:
                with failures_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == []
        for tid in range(n_threads):
            base = tid * per_thread
            for i in range(per_thread):
                if i % 3 == 0:
                    assert not cluster.has("k%d" % (base + i))
                else:
                    assert cluster.get("k%d" % (base + i)) == i
        for info in cluster.status()["shards"].values():
            assert info["backup_healthy"] is True

    def test_concurrent_writes_recover(self, tmp_path):
        journal_dir = str(tmp_path / "journals")
        c1 = KVCluster(4, replication=True, journal_dir=journal_dir)
        n_threads = 8
        per_thread = 25
        barrier = threading.Barrier(n_threads)
        failures = []
        failures_lock = threading.Lock()

        def worker(thread_id):
            try:
                barrier.wait()
                for i in range(per_thread):
                    c1.set("k%d_%d" % (thread_id, i), [thread_id, i])
            except Exception as exc:
                with failures_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert failures == []

        c2 = KVCluster(4, replication=True, journal_dir=journal_dir)
        for tid in range(n_threads):
            for i in range(per_thread):
                assert c2.get("k%d_%d" % (tid, i)) == [tid, i]
        c1.close()
        c2.close()
