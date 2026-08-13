import pytest

from errors import (
    InvalidKeyError,
    KeyNotFoundError,
    KVClusterError,
    ReplicationError,
    ShardDownError,
    StorageFullError,
)
from replica import ReplicaManager
from store import KVCluster, KVStore


def _key_for_shard(shard_manager, shard_id, prefix="k"):
    i = 0
    while True:
        key = f"{prefix}{i}"
        if shard_manager.shard_index(key) == shard_id:
            return key
        i += 1


# --------------------------------------------------------------------- #
# Replication basics
# --------------------------------------------------------------------- #
def test_write_through_replication():
    primary = KVStore(name="p")
    backup = KVStore(name="b")
    rm = ReplicaManager(primary, backup)
    rm.set("a", 1)
    rm.set("b", [1, 2])
    assert primary.get("a") == 1
    assert backup.get("a") == 1
    assert primary.get("b") == [1, 2]
    assert backup.get("b") == [1, 2]
    assert rm.get("a") == 1
    assert rm.size == 2
    assert sorted(rm.keys()) == ["a", "b"]
    assert primary.size == backup.size


def test_delete_is_replicated():
    rm = ReplicaManager(KVStore(name="p"), KVStore(name="b"))
    rm.set("a", 1)
    rm.delete("a")
    assert not rm.has("a")
    assert rm.primary.size == 0
    assert rm.backup.size == 0
    with pytest.raises(KeyNotFoundError):
        rm.delete("a")


# --------------------------------------------------------------------- #
# Replication failure -> rollback + ReplicationError
# --------------------------------------------------------------------- #
def test_backup_full_rolls_back_primary():
    primary = KVStore(name="p")
    backup = KVStore(name="b", max_size=2)
    rm = ReplicaManager(primary, backup)

    rm.set("a", 1)
    rm.set("b", 2)
    with pytest.raises(ReplicationError):
        rm.set("c", 3)

    # primary rolled back: no trace of the failed write
    assert not primary.has("c")
    assert not backup.has("c")
    assert primary.size == 2
    assert backup.size == 2
    assert primary.get("a") == 1 and primary.get("b") == 2

    # cluster still usable: free a slot, then the write succeeds
    rm.delete("a")
    rm.set("c", 3)
    assert primary.get("c") == 3
    assert backup.get("c") == 3


def test_backup_failure_restores_overwritten_value():
    class Boom(KVStore):
        def set(self, key, value):
            raise OSError("backup disk exploded")

    primary = KVStore(name="p")
    backup = Boom(name="b")
    rm = ReplicaManager(primary, backup)
    primary.set("x", 1)  # seed primary directly (backup always fails)

    with pytest.raises(ReplicationError):
        rm.set("x", 2)

    assert primary.get("x") == 1  # old value restored
    assert rm.get("x") == 1
    assert primary.size == 1


def test_replication_does_not_mask_storage_or_key_errors():
    primary = KVStore(name="p", max_size=1)
    backup = KVStore(name="b")
    rm = ReplicaManager(primary, backup)
    rm.set("a", 1)
    with pytest.raises(StorageFullError):
        rm.set("b", 2)  # primary itself is full -> StorageFullError, not ReplicationError
    with pytest.raises(InvalidKeyError):
        rm.set("", 1)


# --------------------------------------------------------------------- #
# Failover semantics
# --------------------------------------------------------------------- #
def test_failover_promotes_backup_with_full_data():
    primary = KVStore(name="p")
    backup = KVStore(name="b")
    rm = ReplicaManager(primary, backup)
    data = {f"k{i}": {"i": i} for i in range(50)}
    for key, value in data.items():
        rm.set(key, value)

    rm.failover()

    # backup became the primary and holds the full dataset
    assert rm.primary is backup
    assert rm.primary.size == 50
    for key, value in data.items():
        assert rm.get(key) == value

    # a fresh backup was rebuilt as a full copy
    assert rm.backup is not primary
    assert rm.backup.size == 50
    for key, value in data.items():
        assert rm.backup.get(key) == value

    # still writable after failover
    rm.set("new", 1)
    assert rm.get("new") == 1
    assert rm.backup.get("new") == 1


def test_failover_repeated_keeps_data():
    primary = KVStore(name="p")
    backup = KVStore(name="b")
    rm = ReplicaManager(primary, backup)
    for i in range(25):
        rm.set(f"k{i}", i)

    rm.failover()
    rm.failover()
    assert rm.size == 25
    for i in range(25):
        assert rm.get(f"k{i}") == i
    assert rm.primary.size == rm.backup.size == 25


def test_cluster_failover_and_continue():
    cluster = KVCluster(shard_count=2, replication=True)
    for i in range(10):
        cluster.set(f"k{i}", i)
    cluster.failover()
    for i in range(10):
        assert cluster.get(f"k{i}") == i
    cluster.set("post", 42)
    assert cluster.get("post") == 42
    for sh in cluster.status()["shards"]:
        assert sh["primary"]["size"] == sh["backup"]["size"]


# --------------------------------------------------------------------- #
# Cluster-level replication failure: other shard unaffected
# --------------------------------------------------------------------- #
def test_cluster_usable_after_replication_failure_on_one_shard():
    def factory(shard_id):
        return ReplicaManager(
            primary=KVStore(name=f"s{shard_id}-p"),
            backup=KVStore(name=f"s{shard_id}-b", max_size=1),
        )

    cluster = KVCluster(shard_count=2, replication=True, shard_store_factory=factory)
    sm = cluster.shard_manager

    k0 = _key_for_shard(sm, 0, prefix="a")
    k1 = _key_for_shard(sm, 0, prefix="b")  # same shard as k0
    ko = _key_for_shard(sm, 1, prefix="c")  # different shard

    cluster.set(k0, 1)  # fills shard-0 backup
    with pytest.raises(ReplicationError):
        cluster.set(k1, 2)  # shard-0 backup full

    # shard 1 keeps working
    cluster.set(ko, 100)
    assert cluster.get(ko) == 100
    assert not cluster.has(k1)

    # shard 0 recovers once a slot is freed
    cluster.delete(k0)
    cluster.set(k1, 2)
    assert cluster.get(k1) == 2
    assert cluster.get(ko) == 100


# --------------------------------------------------------------------- #
# Exception hierarchy
# --------------------------------------------------------------------- #
def test_all_errors_share_base_class():
    for exc in (
        KeyNotFoundError,
        ShardDownError,
        ReplicationError,
        InvalidKeyError,
        StorageFullError,
    ):
        assert issubclass(exc, KVClusterError)
