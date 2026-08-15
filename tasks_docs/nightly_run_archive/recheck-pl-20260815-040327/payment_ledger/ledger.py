"""Double-entry payment ledger with exact Decimal arithmetic.

Amounts are normalized at the entry boundary via ``Decimal(str(amount))`` so
decimal literals are represented exactly (0.1 + 0.2 == 0.3). All state
mutations and reads are guarded by a single lock; ``post`` and
``transfer``/``idempotent_transfer`` are idempotent per ``(account, ref)`` and
bounded by an optional ``max_entries`` capacity.
"""

import threading
import time
from decimal import Decimal, InvalidOperation


class StorageFullError(Exception):
    """Raised when an entry would exceed the ledger's configured capacity."""


class Ledger:
    def __init__(self, max_entries=None):
        if max_entries is not None and max_entries < 0:
            raise ValueError("max_entries must be a non-negative integer or None")
        self._entries = []
        self._seq = 0
        self._seen = set()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def post(self, account, amount, ref):
        with self._lock:
            _check_key(account, ref)
            if (account, ref) in self._seen:
                return False
            amount = _as_amount(amount)
            if self._max_entries is not None and len(self._entries) >= self._max_entries:
                raise StorageFullError(
                    f"ledger capacity {self._max_entries} reached; "
                    f"cannot post {account!r} ref {ref!r}"
                )
            self._append_locked(account, ref, amount)
            return True

    def transfer(self, src, dst, amount, ref):
        return self.idempotent_transfer(src, dst, amount, ref)

    def idempotent_transfer(self, src, dst, amount, ref):
        with self._lock:
            _check_key(src, ref)
            _check_key(dst, ref)
            amount = _as_amount(amount)
            if amount <= 0:
                raise ValueError("transfer amount must be a positive finite amount")
            if (src, ref) in self._seen or (dst, ref) in self._seen:
                return False
            if self._max_entries is not None and len(self._entries) + 2 > self._max_entries:
                raise StorageFullError(
                    f"ledger capacity {self._max_entries} reached; "
                    f"cannot transfer {src!r} -> {dst!r} ref {ref!r}"
                )
            self._append_locked(src, ref, -amount)
            self._append_locked(dst, ref, amount)
            return True

    def balance(self, account):
        with self._lock:
            return sum(
                (e["amount"] for e in self._entries if e["account"] == account),
                Decimal("0"),
            )

    def count(self):
        with self._lock:
            return len(self._entries)

    def last_refs(self, n=10):
        with self._lock:
            return [e["ref"] for e in self._entries[-n:]]

    def _append_locked(self, account, ref, amount):
        self._seq += 1
        self._entries.append({
            "seq": self._seq, "account": account, "amount": amount,
            "ref": ref, "ts": time.time(),
        })
        self._seen.add((account, ref))


def reconcile(ledger, expected_balances):
    mismatches = []
    for account, expected in expected_balances.items():
        want = _as_amount(expected)
        actual = ledger.balance(account)
        if actual != want:
            mismatches.append({
                "account": account,
                "expected": want,
                "actual": actual,
            })
    return {"ok": not mismatches, "mismatches": mismatches}


def _check_key(account, ref):
    if not isinstance(account, str) or not account:
        raise ValueError("account must be a non-empty string")
    if not isinstance(ref, str) or not ref:
        raise ValueError("ref must be a non-empty string")


def _as_amount(value):
    if isinstance(value, Decimal):
        amount = value
    else:
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f"invalid amount: {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"amount must be finite: {value!r}")
    return amount
