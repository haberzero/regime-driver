import threading
import time

import pytest

from ledger import Ledger, reconcile


def test_reconcile_ok_empty_ledger():
    led = Ledger()
    report = reconcile(led, {})
    assert report == {"ok": True, "mismatches": []}


def test_reconcile_ok_all_match():
    led = Ledger()
    led.post("a", 10, "r1")
    led.post("a", 20, "r2")
    led.post("b", 5, "r3")
    report = reconcile(led, {"a": 30, "b": 5})
    assert report["ok"] is True
    assert report["mismatches"] == []


def test_reconcile_exact_comparison_no_tolerance():
    # Legacy reconcile accepted 0.1+0.2 against expected 0.3 because the 1e-9
    # tolerance masked the rounding error. Exact comparison must flag it.
    led = Ledger()
    led.post("a", 10, "r1")
    led.post("a", 20, "r2")
    report = reconcile(led, {"a": 29})  # off by one cent
    assert report["ok"] is False
    assert report["mismatches"] == [
        {"account": "a", "expected": 29, "actual": 30}
    ]


def test_reconcile_multiple_mismatches():
    led = Ledger()
    led.post("a", 10, "r1")
    led.post("b", 100, "r2")
    led.post("c", 1, "r3")
    report = reconcile(led, {"a": 10, "b": 0, "c": 1})
    assert report["ok"] is False
    mismatches = {m["account"]: m for m in report["mismatches"]}
    assert set(mismatches) == {"b"}
    assert mismatches["b"] == {"account": "b", "expected": 0, "actual": 100}


def test_reconcile_surplus_and_missing_accounts():
    led = Ledger()
    led.post("a", 50, "r1")
    # expected mentions a missing account with a nonzero balance -> mismatch;
    # an account present in the ledger but omitted from expected is not flagged
    report = reconcile(led, {"a": 50, "ghost": 7})
    assert report["ok"] is False
    mismatches = {m["account"]: m for m in report["mismatches"]}
    assert "ghost" in mismatches
    assert mismatches["ghost"] == {"account": "ghost", "expected": 7, "actual": 0}


def test_reconcile_reflects_idempotent_state():
    led = Ledger()
    assert led.transfer("src", "dst", 42, "T") is True
    assert led.transfer("src", "dst", 42, "T") is False
    assert reconcile(led, {"src": -42, "dst": 42})["ok"] is True
    assert reconcile(led, {"src": -84, "dst": 84})["ok"] is False


def test_reconcile_report_structure():
    led = Ledger()
    led.post("a", 3, "r1")
    report = reconcile(led, {"a": 5})
    assert set(report.keys()) == {"ok", "mismatches"}
    assert isinstance(report["ok"], bool)
    assert isinstance(report["mismatches"], list)
    assert all(
        set(m.keys()) == {"account", "expected", "actual"} for m in report["mismatches"]
    )


def test_reconcile_single_snapshot_under_concurrency():
    # Every transfer preserves src+dst net == 0, so ANY single snapshot satisfies
    # balance("a") + balance("b") == 0. A report built by reading a then b at
    # different moments would violate it (unless the magnitudes coincidentally
    # match), so any violating report proves reconcile reads a single snapshot.
    led = Ledger()
    stop = threading.Event()
    bad = []

    def poster():
        i = 0
        while not stop.is_set():
            led.transfer("a", "b", 1, "T-%s-%d" % (threading.get_ident(), i))
            i += 1

    def reconciler():
        while not stop.is_set():
            report = reconcile(led, {"a": 0, "b": 0})
            if report["ok"]:
                continue
            actuals = {m["account"]: m["actual"] for m in report["mismatches"]}
            if actuals.get("a", 0) + actuals.get("b", 0) != 0:
                bad.append(report)

    threads = (
        [threading.Thread(target=poster) for _ in range(4)]
        + [threading.Thread(target=reconciler) for _ in range(2)]
    )
    for t in threads:
        t.start()
    time.sleep(0.05)
    stop.set()
    for t in threads:
        t.join()

    assert bad == []
    assert led.balance("a") + led.balance("b") == 0
