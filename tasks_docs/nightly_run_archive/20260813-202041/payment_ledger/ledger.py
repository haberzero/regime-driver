# -*- coding: utf-8 -*-
"""Double-entry payment ledger.

Design decisions (see DESIGN.md):
  * Money is integer cents. Amounts are normalized to whole cents at the API
    boundary via an exact decimal conversion (floats routed through str());
    all stored/returned amounts are ints and all arithmetic is integer
    arithmetic, so "0.1 + 0.2 == 0.3" holds exactly and no tolerance is needed
    when reconciling.
  * post() is idempotent per (account, ref): a duplicate returns False without
    touching the ledger.
  * transfer()/idempotent_transfer() are atomic and idempotent per ref: all
    validation happens before any write, both legs are appended under one lock,
    and a duplicate ref is a no-op returning False.
  * Capacity-limited: max_entries is enforced up-front and raises
    StorageFullError before any mutation.
  * Thread-safe: one lock guards every read and write; balance()/count()
    return consistent snapshots.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from decimal import Decimal


class StorageFullError(Exception):
    """Raised when a posting/transfer would exceed the ledger capacity."""


@dataclass(frozen=True)
class Entry:
    seq: int
    account: str
    amount: int
    ref: str
    ts: float


def to_cents(amount):
    """Normalize an amount (in units) to whole integer cents.

    Floats are routed through str() so that 0.1 maps to exactly 10 cents.
    Non-finite values and sub-cent values are rejected instead of silently
    rounded.
    """
    if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
        raise TypeError("amount must be an int, float or Decimal (in units)")
    if isinstance(amount, float):
        amount = Decimal(str(amount))
    if isinstance(amount, Decimal):
        cents = amount * 100
        if not cents.is_finite():
            raise ValueError("amount %r must be finite" % (amount,))
        if cents != cents.to_integral_value():
            raise ValueError(
                "amount %r has sub-cent precision; pass whole cents" % (amount,)
            )
        return int(cents)
    return amount * 100


class Ledger:
    def __init__(self, max_entries=None):
        if max_entries is not None and (
            not isinstance(max_entries, int)
            or isinstance(max_entries, bool)
            or max_entries < 0
        ):
            raise ValueError("max_entries must be a non-negative int or None")
        self._entries = []
        self._seq = 0
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def _has(self, account, ref):
        for e in self._entries:
            if e.account == account and e.ref == ref:
                return True
        return False

    def _append(self, account, amount_cents, ref):
        self._seq += 1
        self._entries.append(Entry(self._seq, account, amount_cents, ref, time.time()))

    def _ensure_capacity(self, needed):
        if self._max_entries is not None and len(self._entries) + needed > self._max_entries:
            raise StorageFullError(
                "ledger full: %d entries, capacity %d"
                % (len(self._entries) + needed, self._max_entries)
            )

    def post(self, account, amount, ref):
        """Record an entry. Returns True on first posting, False on duplicate."""
        cents = to_cents(amount)
        with self._lock:
            if self._has(account, ref):
                return False
            self._ensure_capacity(1)
            self._append(account, cents, ref)
            return True

    def transfer(self, src, dst, amount, ref):
        """Atomically move money src -> dst. Returns True when applied, False if ref already used."""
        cents = to_cents(amount)
        with self._lock:
            if self._has(src, ref):
                return False
            self._ensure_capacity(2)
            self._append(src, -cents, ref)
            self._append(dst, cents, ref)
            return True

    def idempotent_transfer(self, src, dst, amount, ref):
        """Idempotent transfer: repeated calls with the same ref apply only once."""
        return self.transfer(src, dst, amount, ref)

    def balance(self, account):
        with self._lock:
            return sum(e.amount for e in self._entries if e.account == account)

    def count(self):
        with self._lock:
            return len(self._entries)

    def last_refs(self, n=10):
        with self._lock:
            return [e.ref for e in self._entries[-n:]]


def reconcile(ledger, expected_balances):
    """Compare balances against expected values using exact integer-cents math.

    Returns {"ok": bool, "mismatches": [{"account", "expected", "actual"}]}.
    No tolerance: comparison is exact integer equality.
    """
    mismatches = []
    for acct, want in expected_balances.items():
        want_cents = to_cents(want)
        actual = ledger.balance(acct)
        if actual != want_cents:
            mismatches.append({"account": acct, "expected": want_cents, "actual": actual})
    return {"ok": not mismatches, "mismatches": mismatches}
