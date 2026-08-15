import pytest

from ledger import Ledger, reconcile


def test_reconcile_ok_report():
    ledger = Ledger()
    ledger.post("a", 100, "r1")
    ledger.post("b", 50, "r2")
    report = reconcile(ledger, {"a": 100, "b": 50})
    assert report == {"ok": True, "mismatches": []}


def test_reconcile_mismatch_report_fields():
    ledger = Ledger()
    ledger.post("a", 30, "r1")
    report = reconcile(ledger, {"a": 31})
    assert report["ok"] is False
    assert report["mismatches"] == [
        {"account": "a", "expected": 31, "actual": 30}
    ]


def test_reconcile_multiple_mismatches():
    ledger = Ledger()
    ledger.post("a", 10, "r1")
    ledger.post("b", 20, "r2")
    report = reconcile(ledger, {"a": 11, "b": 21, "c": 5})
    assert report["ok"] is False
    assert len(report["mismatches"]) == 3
    actuals = {m["account"]: m["actual"] for m in report["mismatches"]}
    assert actuals == {"a": 10, "b": 20, "c": 0}


def test_reconcile_exact_no_tolerance():
    ledger = Ledger()
    ledger.post("a", 30, "r1")
    assert reconcile(ledger, {"a": 30})["ok"] is True
    assert reconcile(ledger, {"a": 31})["ok"] is False
    assert reconcile(ledger, {"a": 29})["ok"] is False


def test_reconcile_empty_expected_ok():
    ledger = Ledger()
    ledger.post("a", 5, "r1")
    assert reconcile(ledger, {}) == {"ok": True, "mismatches": []}


def test_reconcile_unknown_account_reported():
    ledger = Ledger()
    report = reconcile(ledger, {"ghost": 10})
    assert report == {
        "ok": False,
        "mismatches": [{"account": "ghost", "expected": 10, "actual": 0}],
    }


def test_reconcile_rejects_sub_cent_expected():
    ledger = Ledger()
    with pytest.raises(ValueError):
        reconcile(ledger, {"a": 0.1})


def test_reconcile_rejects_invalid_account_key():
    ledger = Ledger()
    with pytest.raises(ValueError):
        reconcile(ledger, {5: 10})


def test_reconcile_actual_is_exact_int():
    ledger = Ledger()
    ledger.post("a", 123, "r1")
    report = reconcile(ledger, {"a": 0})
    mismatch = report["mismatches"][0]
    assert mismatch["actual"] == 123
    assert isinstance(mismatch["actual"], int)
