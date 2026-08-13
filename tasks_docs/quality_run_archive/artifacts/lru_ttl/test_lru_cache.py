import random
import threading
import time

import pytest

from lru_cache import LRUCache


def test_invalid_capacity_raises():
    for capacity in (0, -1, -5):
        with pytest.raises(ValueError, match="capacity"):
            LRUCache(capacity)


def test_invalid_ttl_raises():
    for ttl in (0, -1):
        with pytest.raises(ValueError, match="ttl"):
            LRUCache(2, ttl=ttl)


def test_basic_set_get():
    cache = LRUCache(3)
    assert cache.get("a") is None
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("missing", "default") == "default"


def test_get_miss_returns_default():
    cache = LRUCache(2)
    assert cache.get("nope") is None
    assert cache.get("nope", 42) == 42


def test_lru_eviction():
    cache = LRUCache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.has("a") is False
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert cache.size() == 2


def test_get_promotes_most_recent():
    cache = LRUCache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")
    cache.set("c", 3)
    assert cache.has("a") is True
    assert cache.has("b") is False
    assert cache.has("c") is True


def test_set_updates_value_and_promotes():
    cache = LRUCache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("a", 10)
    cache.set("c", 3)
    assert cache.get("a") == 10
    assert cache.has("b") is False
    assert cache.get("c") == 3
    assert cache.size() == 2


def test_has_is_non_destructive():
    cache = LRUCache(2)
    cache.set("a", 1)
    assert cache.has("a") is True
    assert cache.has("a") is True
    assert cache.has("missing") is False
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.has("a") is False


def test_size_and_clear():
    cache = LRUCache(3)
    assert cache.size() == 0
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size() == 2
    cache.clear()
    assert cache.size() == 0
    assert cache.has("a") is False
    assert cache.has("b") is False


def test_size_never_exceeds_capacity():
    cache = LRUCache(2)
    for i in range(100):
        cache.set(i, i)
        assert cache.size() <= 2


def test_capacity_one():
    cache = LRUCache(1)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size() == 1
    assert cache.has("a") is False
    assert cache.get("b") == 2


def test_ttl_not_expired_get_works():
    cache = LRUCache(2, ttl=60)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.has("a") is True


def test_ttl_expired_get_returns_miss():
    cache = LRUCache(2, ttl=0.05)
    cache.set("a", 1)
    assert cache.get("a") == 1
    time.sleep(0.08)
    assert cache.get("a") is None
    assert cache.get("a", 99) == 99


def test_ttl_expired_has_returns_false():
    cache = LRUCache(2, ttl=0.05)
    cache.set("a", 1)
    time.sleep(0.08)
    assert cache.has("a") is False


def test_lazy_expiry_does_not_clear_entry():
    cache = LRUCache(2, ttl=0.05)
    cache.set("a", 1)
    cache.set("b", 2)
    time.sleep(0.08)
    assert cache.has("a") is False
    assert cache.size() == 2
    cache.get("b", None)
    assert cache.size() == 2


def test_ttl_eviction_interaction():
    cache = LRUCache(2, ttl=0.05)
    cache.set("a", 1)
    cache.set("b", 2)
    time.sleep(0.08)
    cache.set("c", 3)
    cache.set("d", 4)
    assert cache.size() == 2
    assert cache.has("c") is True
    assert cache.has("d") is True


def test_stats_empty():
    cache = LRUCache(2)
    stats = cache.stats()
    assert stats == {"hits": 0, "misses": 0, "hit_rate": 0.0}
    assert cache.hits == 0
    assert cache.misses == 0


def test_stats_track_hits_and_misses():
    cache = LRUCache(2)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    assert cache.has("a") is True
    assert cache.has("nope") is False
    assert cache.hits == 2
    assert cache.misses == 2
    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 2
    assert stats["hit_rate"] == pytest.approx(2 / 4)


def test_hit_rate_zero_division_safe():
    cache = LRUCache(2)
    for i in range(100):
        cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 100
    assert stats["hit_rate"] == 0.0


def test_stats_survive_clear():
    cache = LRUCache(2)
    cache.set("a", 1)
    cache.get("a")
    cache.clear()
    assert cache.size() == 0
    assert cache.hits == 1


def test_concurrent_mixed_operations_preserve_set_keys():
    capacity = 32
    num_keys = capacity
    num_threads = 8
    ops_per_thread = 2000
    cache = LRUCache(capacity)
    barrier = threading.Barrier(num_threads)
    seen = set()
    seen_lock = threading.Lock()
    errors = []

    def worker(tid):
        rng = random.Random(tid)
        barrier.wait()
        try:
            for _ in range(ops_per_thread):
                key = rng.randrange(num_keys)
                roll = rng.random()
                if roll < 0.4:
                    cache.set(key, (tid, _))
                    with seen_lock:
                        seen.add(key)
                elif roll < 0.7:
                    cache.get(key)
                else:
                    cache.has(key)
                assert cache.size() <= capacity, "cache grew beyond capacity"
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"threads raised: {errors}"
    assert not any(t.is_alive() for t in threads), "a thread failed to terminate"

    with seen_lock:
        all_set = sorted(seen)
    assert len(all_set) == num_keys, "some keys were never set by any thread"
    for key in all_set:
        assert cache.has(key), f"set key {key} was lost"
    assert cache.size() == num_keys


def test_concurrent_with_overcapacity_allows_eviction():
    capacity = 16
    num_threads = 8
    ops_per_thread = 1000
    cache = LRUCache(capacity)
    barrier = threading.Barrier(num_threads)
    errors = []

    def worker(tid):
        rng = random.Random(1000 + tid)
        barrier.wait()
        try:
            for _ in range(ops_per_thread):
                cache.set(rng.randrange(1000), tid)
                assert cache.size() <= capacity
                cache.get(rng.randrange(1000))
                cache.has(rng.randrange(1000))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"threads raised: {errors}"
    assert not any(t.is_alive() for t in threads), "a thread failed to terminate"
    assert cache.size() <= capacity
