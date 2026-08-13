# -*- coding: utf-8 -*-
from decimal import Decimal

import pytest

from ledger import Ledger, reconcile


def test_report_ok_when_exact_match():
    led = Ledger()
    led.post("a", 0.1, "r1")
    led.post("a", 0.2, "r2")
    led.post("b", 5.0, "r3")
    report = reconcile(led, {"a": 0.3, "b": 5.0})
    assert report == {"ok": True, "mismatches": []}
    assert report["ok"] is True


def test_exact_float_match_no_tolerance():
    # Legacy: float sum 0.1+0.2 == 0.30000000000000004, whose 4e-17 drift was
    # masked by the old 1e-9 tolerance while hiding real rounding errors.
    # Now amounts are integer cents: 10 + 20 == 30 exactly, so the match is
    # exact arithmetic rather than tolerated error.
    led = Ledger()
    led.post("a", 0.1, "r1")
    led.post("a", 0.2, "r2")
    assert led.balance("a") == 30
    assert reconcile(led, {"a": 0.3})["ok"] is True
    # exact comparison: any mismatch is reported with exact integer values
    assert reconcile(led, {"a": 0.29})["ok"] is False


def test_report_ok_int_units_expected():
    led = Ledger()
    led.post("a", 1, "r1")  # 1 unit == 100 cents
    assert reconcile(led, {"a": 1}) == {"ok": True, "mismatches": []}


def test_report_ok_decimal_expected():
    led = Ledger()
    led.post("a", 0.1, "r1")
    assert reconcile(led, {"a": Decimal("0.1")})["ok"] is True


def test_report_mismatch_exact_values():
    led = Ledger()
    led.post("a", 0.1, "r1")
    report = reconcile(led, {"a": 0.31})
    assert report["ok"] is False
    assert report["mismatches"] == [{"account": "a", "expected": 31, "actual": 10}]


def test_report_multiple_mismatches():
    led = Ledger()
    led.post("a", 0.1, "r1")
    led.post("b", 1.0, "r2")
    report = reconcile(led, {"a": 0.2, "b": 2.0, "c": 0})
    assert report["ok"] is False
    by_acct = {m["account"]: m for m in report["mismatches"]}
    assert set(by_acct) == {"a", "b"}
    assert by_acct["a"] == {"account": "a", "expected": 20, "actual": 10}
    assert by_acct["b"] == {"account": "b", "expected": 200, "actual": 100}


def test_report_handles_transfer_state():
    led = Ledger()
    led.transfer("s", "d", 7.0, "t1")
    report = reconcile(led, {"s": -7.0, "d": 7.0})
    assert report == {"ok": True, "mismatches": []}


def test_report_empty_expected():
    led = Ledger()
    assert reconcile(led, {}) == {"ok": True, "mismatches": []}


def test_report_zero_balance_matches_missing_expected():
    led = Ledger()
    assert reconcile(led, {"nobody": 0})["ok"] is True


def test_report_invalid_expected_type():
    led = Ledger()
    with pytest.raises(TypeError):
        reconcile(led, {"a": "1"})
    with pytest.raises(TypeError):
        reconcile(led, {"a": True})


def test_report_invalid_expected_sub_cent():
    led = Ledger()
    with pytest.raises(ValueError):
        reconcile(led, {"a": 0.001})
