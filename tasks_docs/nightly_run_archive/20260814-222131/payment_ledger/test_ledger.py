import threading

import pytest

from ledger import Ledger, StorageFullError, reconcile


def test_post_and_balance_exact_cents():
    ledger = Ledger()
    assert ledger.post("a", 10, "r1") is True
    assert ledger.post("a", 20, "r2") is True
    assert ledger.balance("a") == 30
    assert isinstance(ledger.balance("a"), int)
    assert ledger.balance("missing") == 0
    assert ledger.count() == 2


def test_float_0_1_plus_0_2_scenario_exact():
    ledger = Ledger()
    ledger.post("a", 10, "r1")
    ledger.post("a", 20, "r2")
    assert ledger.balance("a") == 30
    report = reconcile(ledger, {"a": 30})
    assert report["ok"] is True
    assert report["mismatches"] == []


def test_sub_cent_amount_rejected():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.post("a", 0.1, "r")
    with pytest.raises(ValueError):
        ledger.post("a", 0.001, "r")
    with pytest.raises(ValueError):
        ledger.post("a", float("nan"), "r")
    assert ledger.count() == 0


def test_transfer_atomic_success():
    ledger = Ledger()
    assert ledger.transfer("a", "b", 50, "t1") is True
    assert ledger.balance("a") == -50
    assert ledger.balance("b") == 50
    assert ledger.count() == 2


def test_transfer_failure_rolls_back_validation():
    ledger = Ledger()
    ledger.post("a", 100, "seed")
    with pytest.raises(ValueError):
        ledger.transfer("a", "", 50, "t1")
    assert ledger.balance("a") == 100
    assert ledger.balance("b") == 0
    assert ledger.count() == 1


def test_transfer_failure_rolls_back_capacity():
    ledger = Ledger(max_entries=1)
    ledger.post("a", 100, "seed")
    with pytest.raises(StorageFullError):
        ledger.transfer("a", "b", 50, "t1")
    assert ledger.balance("a") == 100
    assert ledger.balance("b") == 0
    assert ledger.count() == 1


def test_transfer_failure_rolls_back_bad_amount():
    ledger = Ledger()
    ledger.post("a", 100, "seed")
    with pytest.raises(ValueError):
        ledger.transfer("a", "b", 0.5, "t1")
    assert ledger.balance("a") == 100
    assert ledger.balance("b") == 0
    assert ledger.count() == 1


def test_transfer_negative_amount_rejected():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.transfer("a", "b", -50, "t1")
    assert ledger.count() == 0


def test_transfer_same_account_rejected():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.transfer("a", "a", 50, "t1")
    assert ledger.count() == 0


def test_post_idempotent_by_account_and_ref():
    ledger = Ledger()
    assert ledger.post("a", 10, "r1") is True
    assert ledger.post("a", 10, "r1") is False
    assert ledger.post("b", 10, "r1") is True
    assert ledger.post("a", 10, "r2") is True
    assert ledger.count() == 3
    assert ledger.balance("a") == 20
    assert ledger.last_refs() == ["r1", "r1", "r2"]


def test_transfer_idempotent_by_ref():
    ledger = Ledger()
    assert ledger.transfer("a", "b", 50, "t1") is True
    assert ledger.transfer("a", "b", 50, "t1") is False
    assert ledger.balance("a") == -50
    assert ledger.balance("b") == 50
    assert ledger.count() == 2


def test_idempotent_transfer_effect_once():
    ledger = Ledger()
    assert ledger.idempotent_transfer("a", "b", 30, "x") is True
    assert ledger.idempotent_transfer("a", "b", 30, "x") is False
    assert ledger.balance("a") == -30
    assert ledger.balance("b") == 30
    assert ledger.count() == 2


def test_storage_full_post():
    ledger = Ledger(max_entries=2)
    assert ledger.post("a", 1, "r1") is True
    assert ledger.post("b", 1, "r2") is True
    with pytest.raises(StorageFullError):
        ledger.post("c", 1, "r3")
    assert ledger.count() == 2


def test_duplicate_at_capacity_is_noop():
    ledger = Ledger(max_entries=1)
    assert ledger.post("a", 1, "r1") is True
    assert ledger.post("a", 1, "r1") is False
    with pytest.raises(StorageFullError):
        ledger.post("a", 1, "r2")
    assert ledger.count() == 1


def test_unbounded_by_default():
    ledger = Ledger()
    for i in range(1000):
        assert ledger.post("a", 1, "r%d" % i) is True
    assert ledger.count() == 1000


def test_invalid_max_entries():
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            Ledger(max_entries=bad)
    Ledger(max_entries=None)
    Ledger(max_entries=5)


@pytest.mark.parametrize("account", ["", None, 1])
def test_invalid_account(account):
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.post(account, 5, "r")


@pytest.mark.parametrize("ref", ["", None, 5])
def test_invalid_ref(ref):
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.post("a", 5, ref)


def test_non_numeric_amount_rejected():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.post("a", "abc", "r")


def test_concurrent_posts_are_consistent():
    ledger = Ledger()
    threads = 8
    per = 500
    barrier = threading.Barrier(threads)

    def worker(tid):
        barrier.wait()
        for i in range(per):
            ledger.post("a", 1, "t%d-%d" % (tid, i))

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert ledger.count() == threads * per
    assert ledger.balance("a") == threads * per


def test_concurrent_duplicate_post_is_single():
    ledger = Ledger()
    threads = 16
    barrier = threading.Barrier(threads)

    def worker():
        barrier.wait()
        ledger.post("a", 5, "dup")

    ts = [threading.Thread(target=worker) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert ledger.count() == 1
    assert ledger.balance("a") == 5


def test_concurrent_transfer_idempotent():
    ledger = Ledger()
    threads = 16
    barrier = threading.Barrier(threads)

    def worker():
        barrier.wait()
        ledger.transfer("a", "b", 10, "t1")

    ts = [threading.Thread(target=worker) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert ledger.count() == 2
    assert ledger.balance("a") == -10
    assert ledger.balance("b") == 10


def test_concurrent_distinct_transfers_exact():
    ledger = Ledger()
    threads = 8
    per = 200

    def worker(tid):
        for i in range(per):
            ledger.transfer("a", "b", 1, "t%d-%d" % (tid, i))

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert ledger.count() == threads * per * 2
    assert ledger.balance("a") == -threads * per
    assert ledger.balance("b") == threads * per
