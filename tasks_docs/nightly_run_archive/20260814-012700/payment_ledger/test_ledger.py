import threading

import pytest

from ledger import Ledger, StorageFullError, reconcile


def test_float_root_cause_010_020():
    # Root cause of the legacy bug: IEEE-754 binary floats cannot represent
    # 0.1/0.2 exactly, so naive accumulation drifts.
    assert 0.1 + 0.2 != 0.3
    # ...and the legacy 1e-9 tolerance is exactly what masked it:
    assert abs((0.1 + 0.2) - 0.3) <= 1e-9
    # The fix: integer cents arithmetic is exact, so posting 10c + 20c
    # reconciles to exactly 30c with no tolerance needed.
    led = Ledger()
    assert led.post("a", 10, "r1") is True
    assert led.post("a", 20, "r2") is True
    assert led.balance("a") == 30
    report = reconcile(led, {"a": 30})
    assert report["ok"] is True
    assert report["mismatches"] == []


def test_float_amounts_rejected():
    led = Ledger()
    with pytest.raises(TypeError):
        led.post("a", 0.1, "r")
    with pytest.raises(TypeError):
        led.transfer("a", "b", 0.1, "r")
    with pytest.raises(TypeError):
        led.post("a", True, "r")  # bool is an int subclass, still reject
    assert led.count() == 0


def test_transfer_atomic_on_storage_full():
    # Legacy bug: post(src) then post(dst) — if the second leg fails, src was
    # already debited. With max_entries=1 a transfer needs 2 slots, so the whole
    # operation must fail before ANY leg is written.
    led = Ledger(max_entries=1)
    with pytest.raises(StorageFullError):
        led.transfer("src", "dst", 100, "T1")
    assert led.count() == 0
    assert led.balance("src") == 0
    assert led.balance("dst") == 0


def test_transfer_atomic_on_bad_amount():
    led = Ledger()
    with pytest.raises(TypeError):
        led.transfer("src", "dst", "not-money", "T1")
    assert led.count() == 0
    assert led.balance("src") == 0
    assert led.balance("dst") == 0


def test_transfer_applies_both_legs():
    led = Ledger()
    assert led.transfer("src", "dst", 250, "T1") is True
    assert led.balance("src") == -250
    assert led.balance("dst") == 250
    assert led.count() == 2


def test_post_idempotent_by_account_ref():
    led = Ledger()
    assert led.post("a", 10, "R") is True
    assert led.post("a", 10, "R") is False   # duplicate (a, R)
    assert led.post("a", 20, "R") is False   # same (account, ref), new amount ignored
    assert led.post("b", 10, "R") is True    # same ref, different account is new
    assert led.count() == 2
    assert led.balance("a") == 10
    assert led.balance("b") == 10


def test_transfer_idempotent_by_ref():
    led = Ledger()
    assert led.transfer("a", "b", 5, "T") is True
    assert led.transfer("a", "b", 5, "T") is False
    assert led.transfer("a", "b", 999, "T") is False  # amount ignored once applied
    assert led.idempotent_transfer("a", "b", 5, "T") is False
    assert led.balance("a") == -5
    assert led.balance("b") == 5
    assert led.count() == 2


def test_idempotent_transfer_new():
    led = Ledger()
    assert led.idempotent_transfer("a", "b", 7, "X") is True
    assert led.idempotent_transfer("a", "b", 7, "X") is False
    assert led.balance("a") == -7
    assert led.balance("b") == 7


def test_max_entries_capacity():
    led = Ledger(max_entries=2)
    assert led.post("a", 1, "r1") is True
    assert led.post("b", 1, "r2") is True
    with pytest.raises(StorageFullError):
        led.post("c", 1, "r3")
    # duplicate on a full ledger is not an error — nothing new is stored
    assert led.post("a", 1, "r1") is False
    with pytest.raises(StorageFullError):
        led.transfer("a", "c", 1, "T")  # needs 2 slots, only 0 free
    assert led.count() == 2


def test_max_entries_default_unlimited():
    led = Ledger()
    for i in range(10000):
        assert led.post("a", 1, "r%d" % i) is True
    assert led.count() == 10000
    assert led.balance("a") == 10000


def test_concurrent_posts_consistent_snapshot():
    led = Ledger()
    n_threads, n_posts = 8, 100
    accounts = 4

    def worker(tid):
        for i in range(n_posts):
            assert led.post("acct%d" % (i % accounts), 1, "r-%d-%d" % (tid, i)) is True

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert led.count() == n_threads * n_posts
    for a in range(accounts):
        expect = sum(
            1
            for t in range(n_threads)
            for i in range(n_posts)
            if i % accounts == a
        )
        assert led.balance("acct%d" % a) == expect


def test_concurrent_transfers():
    led = Ledger()
    n_threads, n_transfers = 8, 50

    def worker(tid):
        for i in range(n_transfers):
            assert led.transfer("src", "dst", 1, "T-%d-%d" % (tid, i)) is True

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = n_threads * n_transfers
    assert led.count() == 2 * total
    assert led.balance("src") == -total
    assert led.balance("dst") == total


def test_transfer_rejects_src_eq_dst():
    led = Ledger()
    with pytest.raises(ValueError):
        led.transfer("a", "a", 5, "P")
    with pytest.raises(ValueError):
        led.idempotent_transfer("a", "a", 5, "P")
    assert led.count() == 0
    assert led.balance("a") == 0


def test_post_and_transfer_ref_namespaces_isolated():
    # A post using ref 'P' on the destination account must NOT be treated as a
    # duplicate of a later transfer that happens to share the ref, and vice
    # versa. Operation type is part of the idempotency key.
    led = Ledger()
    assert led.post("dst", 5, "P") is True
    assert led.transfer("src", "dst", 5, "P") is True
    assert led.transfer("src", "dst", 5, "P") is False  # exact transfer retry still dedups
    assert led.count() == 3
    assert led.balance("src") == -5
    assert led.balance("dst") == 10  # 5 from post + 5 from transfer credit leg


def test_transfer_same_ref_different_src_applies():
    led = Ledger()
    assert led.transfer("s1", "d", 5, "P") is True
    assert led.transfer("s2", "d", 5, "P") is True   # different src = different transfer
    assert led.transfer("s2", "d", 5, "P") is False  # exact triple retry dedups
    assert led.count() == 4
    assert led.balance("s1") == -5
    assert led.balance("s2") == -5
    assert led.balance("d") == 10


def test_transfer_same_ref_different_dst_applies():
    led = Ledger()
    assert led.transfer("s", "d1", 5, "P") is True
    assert led.transfer("s", "d2", 5, "P") is True
    assert led.count() == 4
    assert led.balance("s") == -10
    assert led.balance("d1") == 5
    assert led.balance("d2") == 5


def test_max_entries_validation():
    with pytest.raises(ValueError):
        Ledger(max_entries=-1)
    with pytest.raises(ValueError):
        Ledger(max_entries="10")
    with pytest.raises(ValueError):
        Ledger(max_entries=True)
    Ledger(max_entries=None)
    Ledger(max_entries=0)


def test_snapshot_is_detached_consistent_copy():
    led = Ledger()
    led.post("a", 1, "r1")
    led.post("b", 2, "r2")
    snap = led.snapshot()
    assert isinstance(snap, list)
    assert len(snap) == 2
    assert snap[0].seq == 1 and snap[0].account == "a" and snap[0].amount == 1
    assert snap[1].ref == "r2"
    snap.clear()
    assert led.count() == 2  # mutating the copy never affects the ledger


def test_exception_paths():
    led = Ledger(max_entries=0)
    with pytest.raises(StorageFullError):
        led.post("a", 1, "r1")
    assert led.count() == 0

    led2 = Ledger()
    with pytest.raises(TypeError):
        led2.post("a", None, "r1")
    with pytest.raises(TypeError):
        led2.post("a", "1", "r1")
    with pytest.raises(TypeError):
        led2.post("a", 1.0, "r1")
    assert led2.count() == 0
