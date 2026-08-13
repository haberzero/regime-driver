import threading

import pytest

from errors import (
    InvalidKeyError,
    KeyNotFoundError,
    ShardDownError,
    StorageFullError,
)
from shard import ShardManager
from store import KVCluster, KVStore


# --------------------------------------------------------------------- #
# KVStore basics
# --------------------------------------------------------------------- #
def test_basic_set_get_delete_has_size_keys():
    store = KVStore()
    store.set("a", 1)
    store.set("b", {"x": [1, 2, 3]})
    assert store.get("a") == 1
    assert store.has("a")
    assert not store.has("zzz")
    assert store.size == 2
    assert sorted(store.keys()) == ["a", "b"]
    store.delete("a")
    assert not store.has("a")
    assert store.size == 1
    with pytest.raises(KeyNotFoundError):
        store.get("a")
    with pytest.raises(KeyNotFoundError):
        store.delete("a")


def test_set_overwrites_and_snapshot_semantics():
    store = KVStore()
    store.set("k", 1)
    store.set("k", {"nested": True})
    assert store.get("k") == {"nested": True}
    assert store.size == 1


def test_invalid_key_raises():
    store = KVStore()
    for bad in ["", 1, None, b"bytes", ["a"]]:
        with pytest.raises(InvalidKeyError):
            store.set(bad, 1)
        with pytest.raises(InvalidKeyError):
            store.get(bad)
        with pytest.raises(InvalidKeyError):
            store.delete(bad)


def test_non_json_serializable_value_raises():
    store = KVStore()
    with pytest.raises(TypeError):
        store.set("k", object())


def test_storage_limit():
    store = KVStore(max_size=2)
    store.set("a", 1)
    store.set("b", 2)
    with pytest.raises(StorageFullError):
        store.set("c", 3)
    assert store.size == 2
    store.set("a", 99)  # overwrite existing key is allowed at capacity
    assert store.get("a") == 99
    store.delete("a")
    store.set("c", 3)  # freed slot is reusable
    assert store.get("c") == 3


# --------------------------------------------------------------------- #
# Journal recovery
# --------------------------------------------------------------------- #
def test_journal_recovery_keeps_committed_writes(tmp_path):
    journal = str(tmp_path / "store.jlog")
    store = KVStore(name="s", journal_path=journal)
    store.set("a", 1)
    store.set("b", {"k": "v"})
    store.delete("a")
    store.set("c", [1, 2])
    store.close()

    recovered = KVStore.from_journal(journal)
    assert recovered.get("b") == {"k": "v"}
    assert recovered.get("c") == [1, 2]
    assert not recovered.has("a")
    assert recovered.size == 2


def test_journal_recovery_ignores_torn_trailing_write(tmp_path):
    journal = str(tmp_path / "store.jlog")
    store = KVStore(name="s", journal_path=journal)
    store.set("a", 1)
    store.close()
    with open(journal, "a") as f:
        f.write('{"op": "set", "key": "b", "value":')  # torn write

    recovered = KVStore.from_journal(journal)
    assert recovered.get("a") == 1
    assert not recovered.has("b")


def test_journal_recovery_then_writes_continue(tmp_path):
    journal = str(tmp_path / "store.jlog")
    store = KVStore(name="s", journal_path=journal)
    store.set("a", 1)
    store.close()

    recovered = KVStore.from_journal(journal)
    recovered.set("b", 2)
    recovered.delete("a")

    recovered_again = KVStore.from_journal(journal)
    assert recovered_again.get("b") == 2
    assert not recovered_again.has("a")


def test_no_journal_when_not_configured():
    store = KVStore()
    store.set("a", 1)
    assert store.journal_path is None


def test_constructor_parameter_validation():
    with pytest.raises(ValueError):
        KVStore(name="")
    with pytest.raises(ValueError):
        KVStore(max_size=0)
    with pytest.raises(ValueError):
        KVStore(max_size=-3)
    with pytest.raises(ValueError):
        KVStore(max_size="2")


def test_replication_flag_interface():
    assert KVStore().replication is False
    cluster = KVCluster(shard_count=2, replication=True)
    assert all(store.replication is True for store in cluster.shard_manager.stores)
    cluster_no = KVCluster(shard_count=2, replication=False)
    assert all(store.replication is False for store in cluster_no.shard_manager.stores)
    with pytest.raises(ValueError):
        cluster_no.failover(shard_index=0)


# --------------------------------------------------------------------- #
# Sharding
# --------------------------------------------------------------------- #
def test_shard_routing_is_deterministic_across_instances():
    keys = [f"key-{i}" for i in range(1000)]
    sm1 = ShardManager(4)
    sm2 = ShardManager(4)
    idx1 = [sm1.shard_index(k) for k in keys]
    idx2 = [sm2.shard_index(k) for k in keys]
    assert idx1 == idx2
    assert all(0 <= i < 4 for i in idx1)


def test_shard_routing_places_data_in_correct_shard():
    sm = ShardManager(3)
    for i in range(30):
        sm.set(f"k{i}", i)
    for i in range(30):
        key = f"k{i}"
        assert sm.stores[sm.shard_index(key)].get(key) == i
        assert sm.get(key) == i
    assert sm.size == sum(s.size for s in sm.stores) == 30


def test_shard_down_isolation():
    sm = ShardManager(3)
    for i in range(3):
        sm.set(f"k{i}", i)
    idx = sm.shard_index("k0")

    sm.mark_shard_down(idx)
    assert sm.is_down(idx)
    with pytest.raises(ShardDownError):
        sm.get("k0")
    with pytest.raises(ShardDownError):
        sm.set("k0", 100)
    with pytest.raises(ShardDownError):
        sm.delete("k0")
    with pytest.raises(ShardDownError):
        sm.has("k0")

    # other shards keep working
    other = sm.shard_index("k1")
    assert other != idx
    assert sm.get("k1") == 1
    sm.set("k1", 11)
    assert sm.get("k1") == 11

    sm.mark_shard_up(idx)
    assert not sm.is_down(idx)
    assert sm.get("k0") == 0


def test_shard_invalid_id_raises():
    sm = ShardManager(2)
    with pytest.raises(ValueError):
        sm.mark_shard_down(5)


# --------------------------------------------------------------------- #
# KVCluster facade
# --------------------------------------------------------------------- #
def test_cluster_basic_routing_and_status():
    cluster = KVCluster(shard_count=2, replication=True)
    cluster.set("a", 1)
    cluster.set("b", 2)
    assert cluster.get("a") == 1
    assert cluster.has("b")
    status = cluster.status()
    assert status["shard_count"] == 2
    assert status["replication"] is True
    assert status["total_size"] == 2
    assert len(status["shards"]) == 2
    for sh in status["shards"]:
        assert sh["down"] is False
        assert "primary" in sh and "backup" in sh
        assert sh["primary"]["size"] == sh["backup"]["size"]


def test_cluster_no_replication():
    cluster = KVCluster(shard_count=2, replication=False)
    cluster.set("a", 1)
    status = cluster.status()
    assert status["replication"] is False
    assert "primary" not in status["shards"][0]
    assert "backup" not in status["shards"][0]


def test_cluster_failover_all_shards_keeps_data():
    cluster = KVCluster(shard_count=3, replication=True)
    for i in range(20):
        cluster.set(f"k{i}", {"i": i})
    cluster.failover()
    assert cluster.size == 20
    for i in range(20):
        assert cluster.get(f"k{i}") == {"i": i}
    for sh in cluster.status()["shards"]:
        assert sh["primary"]["size"] == sh["backup"]["size"]
        assert sh["size"] == sh["primary"]["size"]


def test_cluster_shard_down_and_up():
    cluster = KVCluster(shard_count=2, replication=True)
    idx = cluster.shard_manager.shard_index("a")
    # find a key on the *other* shard so isolation is observable
    other = 1 - idx
    i = 0
    while cluster.shard_manager.shard_index(f"z{i}") != other:
        i += 1
    key_other = f"z{i}"
    cluster.set("a", 1)
    cluster.set(key_other, 2)
    cluster.mark_shard_down(idx)
    with pytest.raises(ShardDownError):
        cluster.get("a")
    assert cluster.get(key_other) == 2  # unaffected
    assert cluster.status()["shards"][idx]["down"] is True
    cluster.mark_shard_up(idx)
    assert cluster.get("a") == 1


def test_cluster_invalid_key_raises():
    cluster = KVCluster(shard_count=2, replication=True)
    with pytest.raises(InvalidKeyError):
        cluster.set("", 1)


# --------------------------------------------------------------------- #
# Concurrency: 8 threads against one cluster, barrier start
# --------------------------------------------------------------------- #
def test_concurrent_cluster_no_data_loss_no_exception_leak():
    cluster = KVCluster(shard_count=4, replication=True)
    n_threads = 8
    per_thread = 40
    barrier = threading.Barrier(n_threads)
    errors = []

    def worker(tid):
        try:
            barrier.wait(timeout=10)
            for i in range(per_thread):
                cluster.set(f"t{tid}-k{i}", {"tid": tid, "i": i})
            for i in range(per_thread):
                value = cluster.get(f"t{tid}-k{i}")
                assert value == {"tid": tid, "i": i}, (tid, i, value)
            for i in range(per_thread):
                if i % 2 == 0:
                    cluster.delete(f"t{tid}-k{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append((tid, type(exc).__name__, str(exc)))

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"exceptions leaked from workers: {errors}"
    for tid in range(n_threads):
        for i in range(per_thread):
            key = f"t{tid}-k{i}"
            if i % 2 == 0:
                assert not cluster.has(key)
            else:
                assert cluster.get(key) == {"tid": tid, "i": i}
    assert cluster.size == n_threads * (per_thread // 2)


def test_concurrent_single_shard_store():
    store = KVStore(name="s")
    n_threads = 8
    per_thread = 100
    barrier = threading.Barrier(n_threads)
    errors = []

    def worker(tid):
        try:
            barrier.wait(timeout=10)
            for i in range(per_thread):
                store.set(f"t{tid}-{i}", i)
        except Exception as exc:  # noqa: BLE001
            errors.append((tid, type(exc).__name__, str(exc)))

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert store.size == n_threads * per_thread
    for tid in range(n_threads):
        for i in range(per_thread):
            assert store.get(f"t{tid}-{i}") == i
