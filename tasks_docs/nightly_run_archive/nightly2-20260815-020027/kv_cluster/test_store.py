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
from shard import ShardManager
from store import KVStore


class TestExceptions:
    def test_hierarchy(self):
        for exc_type in (
            KeyNotFoundError,
            ShardDownError,
            ReplicationError,
            InvalidKeyError,
            StorageFullError,
        ):
            assert issubclass(exc_type, KVClusterError)
            assert issubclass(exc_type, Exception)


class TestKVStoreBasics:
    def test_set_get(self):
        store = KVStore()
        store.set("name", "alice")
        assert store.get("name") == "alice"

    def test_set_json_values(self):
        store = KVStore()
        payload = {"list": [1, 2, {"n": 3}], "flag": True, "nil": None}
        store.set("obj", payload)
        assert store.get("obj") == payload

    def test_get_missing_raises(self):
        store = KVStore()
        with pytest.raises(KeyNotFoundError):
            store.get("nope")

    def test_delete_missing_raises(self):
        store = KVStore()
        with pytest.raises(KeyNotFoundError):
            store.delete("nope")

    def test_has_size_keys(self):
        store = KVStore()
        assert store.size == 0
        store.set("a", 1)
        store.set("b", 2)
        assert store.has("a") and store.has("b")
        assert not store.has("c")
        assert store.size == 2
        assert sorted(store.keys()) == ["a", "b"]
        store.delete("a")
        assert store.size == 1
        assert store.keys() == ["b"]

    def test_invalid_key_raises(self):
        store = KVStore()
        for key in (None, "", 123, ["a"]):
            with pytest.raises(InvalidKeyError):
                store.set(key, 1)
            with pytest.raises(InvalidKeyError):
                store.get(key)
            with pytest.raises(InvalidKeyError):
                store.delete(key)
            with pytest.raises(InvalidKeyError):
                store.has(key)

    def test_non_json_value_raises(self):
        store = KVStore()
        with pytest.raises(ValueError):
            store.set("bad", {1, 2})
        with pytest.raises(ValueError):
            store.set("bad", object())


class TestStorageLimit:
    def test_storage_full(self):
        store = KVStore(max_size=2)
        store.set("a", 1)
        store.set("b", 2)
        with pytest.raises(StorageFullError):
            store.set("c", 3)
        assert store.size == 2

    def test_overwrite_existing_key_allowed(self):
        store = KVStore(max_size=1)
        store.set("a", 1)
        store.set("a", 100)
        assert store.get("a") == 100
        with pytest.raises(StorageFullError):
            store.set("b", 2)

    def test_invalid_max_size(self):
        with pytest.raises(ValueError):
            KVStore(max_size=-1)


class TestJournalRecovery:
    def test_recover_after_reopen(self, tmp_path):
        path = str(tmp_path / "store.log")
        store = KVStore(journal_path=path)
        store.set("a", 1)
        store.set("b", {"x": [1, 2]})
        store.delete("a")
        store.close()

        recovered = KVStore(journal_path=path)
        assert recovered.size == 1
        assert not recovered.has("a")
        assert recovered.get("b") == {"x": [1, 2]}
        recovered.close()

    def test_recover_after_crash_simulation(self, tmp_path):
        path = str(tmp_path / "store.log")
        store = KVStore(journal_path=path)
        for i in range(50):
            store.set("key%d" % i, i)

        recovered = KVStore(journal_path=path)
        assert recovered.size == 50
        for i in range(50):
            assert recovered.get("key%d" % i) == i
        store.close()
        recovered.close()

    def test_torn_tail_line_ignored(self, tmp_path):
        path = str(tmp_path / "store.log")
        store = KVStore(journal_path=path)
        store.set("a", 1)
        store.close()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"op":"set","key":"b","value":2')
        recovered = KVStore(journal_path=path)
        assert recovered.has("a")
        assert not recovered.has("b")
        recovered.close()


class TestKVStoreConcurrency:
    def test_8_threads_no_data_loss(self):
        store = KVStore()
        n_threads = 8
        per_thread = 100
        barrier = threading.Barrier(n_threads)
        failures = []
        failures_lock = threading.Lock()

        def worker(thread_id):
            try:
                barrier.wait()
                base = thread_id * per_thread
                for i in range(per_thread):
                    store.set("k%d" % (base + i), i)
                for i in range(per_thread):
                    assert store.get("k%d" % (base + i)) == i
                for i in range(0, per_thread, 2):
                    store.delete("k%d" % (base + i))
            except Exception as exc:
                with failures_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == []
        assert store.size == n_threads * (per_thread // 2)
        for tid in range(n_threads):
            base = tid * per_thread
            for i in range(per_thread):
                if i % 2 == 0:
                    assert not store.has("k%d" % (base + i))
                else:
                    assert store.get("k%d" % (base + i)) == i


class TestShardManager:
    def _manager(self, shard_count=4):
        return ShardManager(shard_count, lambda shard_id: KVStore())

    def test_routing_deterministic(self):
        for key in ("alpha", "beta", "gamma", "k1", "k2"):
            assert ShardManager.shard_id_for(key, 5) == ShardManager.shard_id_for(key, 5)

    def test_routing_covers_all_shards(self):
        seen = set()
        i = 0
        while len(seen) < 4 and i < 10000:
            seen.add(ShardManager.shard_id_for("key%d" % i, 4))
            i += 1
        assert seen == {0, 1, 2, 3}

    def test_invalid_key_routing(self):
        with pytest.raises(InvalidKeyError):
            ShardManager.shard_id_for(None, 4)

    def test_set_get_route_to_same_shard(self):
        manager = self._manager(4)
        manager.set("hello", 42)
        shard_id = ShardManager.shard_id_for("hello", 4)
        assert manager.get_store(shard_id).get("hello") == 42
        assert manager.get("hello") == 42

    def test_isolation_down_shard(self):
        manager = self._manager(4)
        target = next(
            "iso%d" % i
            for i in range(1000)
            if ShardManager.shard_id_for("iso%d" % i, 4) == 0
        )
        other = next(
            "other%d" % i
            for i in range(1000)
            if ShardManager.shard_id_for("other%d" % i, 4) != 0
        )
        manager.set(target, 1)
        manager.set(other, 2)

        manager.mark_shard_down(0)
        with pytest.raises(ShardDownError):
            manager.get(target)
        with pytest.raises(ShardDownError):
            manager.set(target, 9)
        with pytest.raises(ShardDownError):
            manager.delete(target)
        with pytest.raises(ShardDownError):
            manager.has(target)

        assert manager.get(other) == 2
        manager.set(other, 5)
        assert manager.get(other) == 5

        manager.mark_shard_up(0)
        assert manager.get(target) == 1

    def test_invalid_shard_id(self):
        manager = self._manager(3)
        with pytest.raises(ValueError):
            manager.mark_shard_down(5)
