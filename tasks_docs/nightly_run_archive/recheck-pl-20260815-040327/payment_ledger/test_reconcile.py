from decimal import Decimal

import pytest

from ledger import Ledger, reconcile


def test_reconcile_ok_empty_mismatches():
    ledger = Ledger()
    ledger.post("a", "1.00", "r1")
    ledger.post("b", "2.00", "r2")
    report = reconcile(ledger, {"a": "1.00", "b": "2.00"})
    assert report == {"ok": True, "mismatches": []}


def test_reconcile_empty_ledger_ok():
    ledger = Ledger()
    report = reconcile(ledger, {})
    assert report == {"ok": True, "mismatches": []}


def test_reconcile_reports_single_mismatch():
    ledger = Ledger()
    ledger.post("a", "1.00", "r1")
    report = reconcile(ledger, {"a": "1.50"})
    assert report["ok"] is False
    assert report["mismatches"] == [
        {"account": "a", "expected": Decimal("1.50"), "actual": Decimal("1.00")}
    ]


def test_reconcile_exact_comparison_no_epsilon():
    ledger = Ledger()
    ledger.post("a", 0.1, "r1")
    ledger.post("a", 0.2, "r2")
    report = reconcile(ledger, {"a": 0.3})
    assert report["ok"] is True
    assert report["mismatches"] == []

    ledger2 = Ledger()
    ledger2.post("a", "0.30000000000000004", "r1")
    report2 = reconcile(ledger2, {"a": "0.3"})
    assert report2["ok"] is False
    assert report2["mismatches"][0]["account"] == "a"
    assert report2["mismatches"][0]["expected"] == Decimal("0.3")
    assert report2["mismatches"][0]["actual"] == Decimal("0.30000000000000004")


def test_reconcile_multiple_mismatches():
    ledger = Ledger()
    ledger.post("a", "1.00", "r1")
    ledger.post("b", "1.00", "r2")
    report = reconcile(ledger, {"a": "9.00", "b": "9.00", "c": "0.00"})
    assert report["ok"] is False
    accts = {m["account"] for m in report["mismatches"]}
    assert accts == {"a", "b"}
    assert all(m["account"] != "c" for m in report["mismatches"])


def test_reconcile_expected_types_normalized():
    ledger = Ledger()
    ledger.post("a", "0.1", "r1")
    assert reconcile(ledger, {"a": "0.1"})["ok"] is True
    assert reconcile(ledger, {"a": 0.1})["ok"] is True
    assert reconcile(ledger, {"a": Decimal("0.1")})["ok"] is True


def test_reconcile_after_transfer_balances():
    ledger = Ledger()
    ledger.transfer("a", "b", "5.00", "t1")
    report = reconcile(ledger, {"a": "-5.00", "b": "5.00"})
    assert report["ok"] is True


def test_reconcile_rejects_invalid_expected_amount():
    ledger = Ledger()
    with pytest.raises(ValueError):
        reconcile(ledger, {"a": "not-a-number"})
