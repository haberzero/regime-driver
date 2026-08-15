import threading
import time
from decimal import Decimal

import pytest

from ledger import Ledger, StorageFullError


def test_post_returns_true_for_new_entry():
    ledger = Ledger()
    assert ledger.post("alice", "0.10", "r1") is True
    assert ledger.count() == 1


def test_post_duplicate_ref_returns_false():
    ledger = Ledger()
    assert ledger.post("alice", "0.10", "r1") is True
    assert ledger.post("alice", "0.10", "r1") is False
    assert ledger.post("alice", "0.10", "r1") is False
    assert ledger.count() == 1
    assert ledger.balance("alice") == Decimal("0.10")


def test_post_same_ref_different_account_is_allowed():
    ledger = Ledger()
    assert ledger.post("alice", "0.10", "r1") is True
    assert ledger.post("bob", "0.10", "r1") is True
    assert ledger.count() == 2


def test_float_root_cause_0_1_plus_0_2_is_exact():
    ledger = Ledger()
    assert ledger.post("a", 0.1, "x1") is True
    assert ledger.post("a", 0.2, "x2") is True
    assert ledger.balance("a") == Decimal("0.3")
    assert ledger.balance("a") != 0.30000000000000004


def test_negative_amount_post_allowed():
    ledger = Ledger()
    assert ledger.post("a", "-0.10", "n1") is True
    assert ledger.balance("a") == Decimal("-0.10")


def test_transfer_moves_funds_atomically():
    ledger = Ledger()
    assert ledger.transfer("alice", "bob", "1.00", "t1") is True
    assert ledger.balance("alice") == Decimal("-1.00")
    assert ledger.balance("bob") == Decimal("1.00")
    assert ledger.count() == 2


def test_transfer_duplicate_ref_only_books_once():
    ledger = Ledger()
    assert ledger.transfer("alice", "bob", "1.00", "t1") is True
    assert ledger.transfer("alice", "bob", "1.00", "t1") is False
    assert ledger.balance("alice") == Decimal("-1.00")
    assert ledger.balance("bob") == Decimal("1.00")
    assert ledger.count() == 2


def test_transfer_atomic_on_invalid_amount():
    ledger = Ledger()
    assert ledger.post("alice", "10.00", "seed") is True
    with pytest.raises(ValueError):
        ledger.transfer("alice", "bob", float("nan"), "bad")
    assert ledger.balance("alice") == Decimal("10.00")
    assert ledger.balance("bob") == Decimal("0")
    assert ledger.count() == 1


def test_transfer_atomic_on_non_positive_amount():
    ledger = Ledger()
    assert ledger.post("alice", "10.00", "seed") is True
    with pytest.raises(ValueError):
        ledger.transfer("alice", "bob", "-1.00", "neg")
    with pytest.raises(ValueError):
        ledger.transfer("alice", "bob", "0", "zero")
    assert ledger.balance("alice") == Decimal("10.00")
    assert ledger.balance("bob") == Decimal("0")
    assert ledger.count() == 1


def test_transfer_atomic_when_capacity_full():
    ledger = Ledger(max_entries=2)
    assert ledger.post("alice", "10.00", "seed") is True
    with pytest.raises(StorageFullError):
        ledger.transfer("alice", "bob", "1.00", "t1")
    assert ledger.balance("alice") == Decimal("10.00")
    assert ledger.balance("bob") == Decimal("0")
    assert ledger.count() == 1


def test_idempotent_transfer_repeat_returns_false():
    ledger = Ledger()
    assert ledger.idempotent_transfer("alice", "bob", "2.00", "it1") is True
    assert ledger.idempotent_transfer("alice", "bob", "2.00", "it1") is False
    assert ledger.balance("alice") == Decimal("-2.00")
    assert ledger.balance("bob") == Decimal("2.00")
    assert ledger.count() == 2


def test_capacity_storage_full_error():
    ledger = Ledger(max_entries=2)
    assert ledger.post("a", "1.00", "r1") is True
    assert ledger.post("b", "1.00", "r2") is True
    with pytest.raises(StorageFullError):
        ledger.post("c", "1.00", "r3")
    assert ledger.count() == 2
    assert ledger.balance("c") == Decimal("0")


def test_capacity_duplicate_when_full_returns_false():
    ledger = Ledger(max_entries=1)
    assert ledger.post("a", "1.00", "r1") is True
    assert ledger.post("a", "1.00", "r1") is False
    assert ledger.count() == 1


def test_max_entries_zero_always_full():
    ledger = Ledger(max_entries=0)
    with pytest.raises(StorageFullError):
        ledger.post("a", "1.00", "r1")
    assert ledger.count() == 0


def test_max_entries_none_unlimited():
    ledger = Ledger()
    for i in range(1000):
        assert ledger.post("a", "0.01", f"r{i}") is True
    assert ledger.count() == 1000


def test_negative_max_entries_rejected():
    with pytest.raises(ValueError):
        Ledger(max_entries=-1)


def test_balance_exact_for_repeated_decimal_amounts():
    ledger = Ledger()
    for i in range(3):
        ledger.post("a", "0.10", f"r{i}")
    assert ledger.balance("a") == Decimal("0.30")


def test_invalid_amount_raises_value_error():
    ledger = Ledger()
    for bad in (float("nan"), float("inf"), None, "abc"):
        with pytest.raises(ValueError):
            ledger.post("a", bad, f"r{bad!r}")


def test_invalid_account_raises_value_error():
    ledger = Ledger()
    for bad in ("", None, 123):
        with pytest.raises(ValueError):
            ledger.post(bad, "1.00", "r1")


def test_invalid_ref_raises_value_error():
    ledger = Ledger()
    for bad in ("", None, 123):
        with pytest.raises(ValueError):
            ledger.post("a", "1.00", bad)


def test_concurrent_posts_consistent():
    threads = 8
    posts_per_thread = 200
    ledger = Ledger()

    def worker(tid):
        for i in range(posts_per_thread):
            ledger.post(f"acct-{tid % 2}", "0.01", f"t{tid}-{i}")

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert ledger.count() == threads * posts_per_thread
    expected = Decimal(threads // 2 * posts_per_thread) * Decimal("0.01")
    assert ledger.balance("acct-0") == expected
    assert ledger.balance("acct-1") == expected
    seqs = [e["seq"] for e in ledger._entries]
    assert len(set(seqs)) == len(seqs)


def test_concurrent_reads_are_safe():
    ledger = Ledger()
    assert ledger.post("a", "0.00", "seed") is True
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            ledger.post("a", "0.01", f"w{i}")
            i += 1

    def reader():
        while not stop.is_set():
            ledger.balance("a")
            ledger.count()

    w = threading.Thread(target=writer)
    readers = [threading.Thread(target=reader) for _ in range(4)]
    w.start()
    for r in readers:
        r.start()
    time.sleep(0.2)
    stop.set()
    w.join()
    for r in readers:
        r.join()
    assert ledger.count() >= 1
    assert ledger.balance("a") == Decimal(str(ledger.count() - 1)) * Decimal("0.01")
