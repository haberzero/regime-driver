# -*- coding: utf-8 -*-
import threading

import pytest

from ledger import Ledger, StorageFullError


# --- Defect 1: floating-point drift root cause -----------------------------
def test_float_root_cause_0_1_plus_0_2():
    led = Ledger()
    assert led.post("a", 0.1, "r1")
    assert led.post("a", 0.2, "r2")
    # Legacy float sum was 0.30000000000000004 (binary float drift);
    # int-cents arithmetic is exact: 10 + 20 == 30 cents.
    assert led.balance("a") == 30
    assert led.balance("a") / 100 == 0.3


def test_float_negative_and_whole_units():
    led = Ledger()
    assert led.post("a", 1, "r1")
    assert led.post("a", -0.5, "r2")
    assert led.balance("a") == 50


def test_amounts_stored_as_int_cents():
    led = Ledger()
    led.post("a", 0.1, "r1")
    e = led._entries[0]
    assert isinstance(e.amount, int)
    assert e.amount == 10


# --- Defect 2: transfer atomicity -------------------------------------------
def test_transfer_applies_both_legs():
    led = Ledger()
    assert led.transfer("src", "dst", 5.0, "t1")
    assert led.balance("src") == -500
    assert led.balance("dst") == 500
    assert led.count() == 2


def test_transfer_atomic_on_capacity_failure():
    led = Ledger(max_entries=1)
    with pytest.raises(StorageFullError):
        led.transfer("src", "dst", 10, "t1")
    assert led.balance("src") == 0
    assert led.balance("dst") == 0
    assert led.count() == 0


def test_transfer_atomic_on_invalid_amount():
    led = Ledger()
    with pytest.raises(ValueError):
        led.transfer("src", "dst", 0.001, "t1")
    assert led.count() == 0
    assert led.balance("src") == 0
    assert led.balance("dst") == 0


def test_transfer_capacity_full_no_partial():
    led = Ledger(max_entries=3)
    led.post("a", 1, "r1")
    led.post("b", 1, "r2")
    with pytest.raises(StorageFullError):
        led.transfer("x", "y", 1, "t1")  # needs 2 slots, only 1 left
    assert led.count() == 2
    assert led.balance("x") == 0
    assert led.balance("y") == 0


# --- Defect 3: idempotency ---------------------------------------------------
def test_post_idempotent_duplicate():
    led = Ledger()
    assert led.post("a", 0.10, "ref-x")
    assert not led.post("a", 0.10, "ref-x")
    assert led.balance("a") == 10
    assert led.count() == 1
    # same ref, different account is a distinct key -> allowed
    assert led.post("b", 0.10, "ref-x")
    assert led.count() == 2


def test_transfer_idempotent_by_ref():
    led = Ledger()
    assert led.transfer("s", "d", 100, "t")
    assert not led.transfer("s", "d", 100, "t")
    assert not led.idempotent_transfer("s", "d", 100, "t")
    assert led.balance("s") == -10000
    assert led.balance("d") == 10000
    assert led.count() == 2


def test_idempotent_transfer_returns_first_time():
    led = Ledger()
    assert led.idempotent_transfer("a", "b", 1, "t1") is True
    assert led.idempotent_transfer("a", "b", 1, "t1") is False


def test_duplicate_post_at_capacity_returns_false_not_error():
    led = Ledger(max_entries=1)
    assert led.post("a", 1, "r1")
    assert not led.post("a", 1, "r1")


# --- Defect 4: capacity ------------------------------------------------------
def test_capacity_limit():
    led = Ledger(max_entries=2)
    assert led.post("a", 1, "r1")
    assert led.post("b", 1, "r2")
    with pytest.raises(StorageFullError):
        led.post("c", 1, "r3")
    assert led.count() == 2
    assert led.balance("c") == 0


def test_capacity_zero():
    led = Ledger(max_entries=0)
    with pytest.raises(StorageFullError):
        led.post("a", 1, "r1")
    assert led.count() == 0


def test_max_entries_validation():
    with pytest.raises(ValueError):
        Ledger(max_entries=-1)
    with pytest.raises(ValueError):
        Ledger(max_entries="lots")
    with pytest.raises(ValueError):
        Ledger(max_entries=True)


def test_unbounded_by_default():
    led = Ledger()
    for i in range(1000):
        led.post("a", 1, "r%d" % i)
    assert led.count() == 1000


# --- Defect 5: concurrency ---------------------------------------------------
def test_concurrent_unique_posts_consistent():
    led = Ledger()
    n_threads, per = 8, 250
    refs = ["u%d" % i for i in range(n_threads * per)]

    def worker(offset):
        for i in range(per):
            led.post("a", 0.01, refs[offset + i])

    threads = [threading.Thread(target=worker, args=(t * per,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert led.count() == n_threads * per
    assert led.balance("a") == n_threads * per


def test_concurrent_same_ref_applied_once():
    led = Ledger()
    results = []

    def worker():
        results.append(led.post("a", 0.01, "shared"))

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert results.count(False) == 49
    assert led.count() == 1
    assert led.balance("a") == 1


def test_concurrent_per_account_balances():
    led = Ledger()
    n_threads = 6

    def worker(acct):
        for i in range(100):
            led.post(acct, 0.01, "%s-%d" % (acct, i))

    threads = [threading.Thread(target=worker, args=("acct%d" % t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for t in range(n_threads):
        assert led.balance("acct%d" % t) == 100
    assert led.count() == n_threads * 100


def test_balance_consistent_snapshot_while_posting():
    led = Ledger()
    for i in range(100):
        led.post("a", 0.01, "seed%d" % i)
    stop = threading.Event()
    seen = set()

    def reader():
        while not stop.is_set():
            seen.add(led.balance("a"))

    def writer():
        for i in range(200):
            led.post("a", 0.01, "w%d" % i)

    r = threading.Thread(target=reader)
    w = threading.Thread(target=writer)
    r.start()
    w.start()
    w.join()
    stop.set()
    r.join()
    assert led.balance("a") == 300
    # every read saw a consistent value inside the valid range (no torn reads)
    assert seen
    assert all(100 <= v <= 300 for v in seen)


# --- Exception paths ----------------------------------------------------------
def test_invalid_amount_type():
    led = Ledger()
    with pytest.raises(TypeError):
        led.post("a", "1", "r1")
    with pytest.raises(TypeError):
        led.post("a", None, "r1")
    with pytest.raises(TypeError):
        led.post("a", True, "r1")
    with pytest.raises(TypeError):
        led.transfer("a", "b", "x", "t1")
    assert led.count() == 0


def test_sub_cent_rejected():
    led = Ledger()
    with pytest.raises(ValueError):
        led.post("a", 0.001, "r1")
    with pytest.raises(ValueError):
        led.transfer("a", "b", 0.001, "t1")
    assert led.count() == 0


def test_non_finite_amounts_rejected():
    led = Ledger()
    with pytest.raises(ValueError):
        led.post("a", float("inf"), "r1")
    with pytest.raises(ValueError):
        led.post("a", float("-inf"), "r1")
    with pytest.raises(ValueError):
        led.post("a", float("nan"), "r1")
    assert led.count() == 0


def test_last_refs():
    led = Ledger()
    led.post("a", 1, "r1")
    led.post("b", 1, "r2")
    led.post("c", 1, "r3")
    assert led.last_refs() == ["r1", "r2", "r3"]
    assert led.last_refs(2) == ["r2", "r3"]
