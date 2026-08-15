"""Double-entry payment ledger.

Money is represented as exact integer cents throughout the public API:
post/transfer amounts are whole cents, balance() returns whole cents, and
reconcile expected/actual values are whole cents. Floating point dollars
(e.g. 0.1) are rejected because they would silently re-introduce 0.1+0.2
arithmetic errors; sub-cent precision raises ValueError.
"""

import threading
import time
from decimal import Decimal, InvalidOperation


class StorageFullError(Exception):
    """Raised when an operation would exceed the ledger's max_entries capacity."""


def _require_account(account):
    if not isinstance(account, str) or account == "":
        raise ValueError("account must be a non-empty string")
    return account


def _require_ref(ref):
    if not isinstance(ref, str) or ref == "":
        raise ValueError("ref must be a non-empty string")
    return ref


def _to_cents(value, what="amount"):
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a whole number of cents, got {value!r}")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a number, got {value!r}") from None
    if not decimal_value.is_finite():
        raise ValueError(f"{what} must be finite, got {value!r}")
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"{what} must be a whole number of cents, got {value!r}")
    return int(decimal_value)


class Ledger:
    def __init__(self, max_entries=None):
        if max_entries is not None and (
            not isinstance(max_entries, int)
            or isinstance(max_entries, bool)
            or max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive int or None")
        self._max_entries = max_entries
        self._entries = []
        self._seen = set()
        self._seq = 0
        self._lock = threading.RLock()

    def _ensure_capacity(self, extra):
        if self._max_entries is not None and len(self._entries) + extra > self._max_entries:
            raise StorageFullError(
                f"ledger capacity of {self._max_entries} entries exceeded"
            )

    def _build_entry(self, account, amount_cents, ref):
        self._seq += 1
        return {
            "seq": self._seq,
            "account": account,
            "amount": amount_cents,
            "ref": ref,
            "ts": time.time(),
        }

    def post(self, account, amount, ref):
        """Book one entry. Returns True if newly booked, False if an entry for
        (account, ref) already exists (idempotent no-op)."""
        account = _require_account(account)
        ref = _require_ref(ref)
        amount_cents = _to_cents(amount)
        with self._lock:
            key = (account, ref)
            if key in self._seen:
                return False
            self._ensure_capacity(1)
            self._entries.append(self._build_entry(account, amount_cents, ref))
            self._seen.add(key)
            return True

    def transfer(self, src, dst, amount, ref):
        """Atomically move amount cents from src to dst. Both legs are booked
        together or not at all. Returns True if newly applied, False if this
        transfer (identified by ref) already happened."""
        src = _require_account(src)
        dst = _require_account(dst)
        if src == dst:
            raise ValueError("src and dst must be different accounts")
        ref = _require_ref(ref)
        amount_cents = _to_cents(amount)
        if amount_cents <= 0:
            raise ValueError(
                "transfer amount must be positive, got {!r}".format(amount)
            )
        with self._lock:
            if (src, ref) in self._seen or (dst, ref) in self._seen:
                return False
            self._ensure_capacity(2)
            start = len(self._entries)
            try:
                self._entries.append(self._build_entry(src, -amount_cents, ref))
                self._entries.append(self._build_entry(dst, amount_cents, ref))
                self._seen.add((src, ref))
                self._seen.add((dst, ref))
            except Exception:
                del self._entries[start:]
                self._seen.discard((src, ref))
                self._seen.discard((dst, ref))
                raise
            return True

    def idempotent_transfer(self, src, dst, amount, ref):
        """Idempotent transfer: repeated calls with the same ref take effect
        only once. Returns True if this call newly applied, False otherwise."""
        return self.transfer(src, dst, amount, ref)

    def balance(self, account):
        """Total booked cents for account (exact integer), 0 if unknown."""
        with self._lock:
            return sum(
                entry["amount"]
                for entry in self._entries
                if entry["account"] == account
            )

    def count(self):
        with self._lock:
            return len(self._entries)

    def last_refs(self, n=10):
        with self._lock:
            return [entry["ref"] for entry in self._entries[-n:]]


def reconcile(ledger, expected_balances):
    """Compare ledger balances against expected_balances (in whole cents).

    Returns {"ok": bool, "mismatches": [{"account", "expected", "actual"}]}.
    Comparison is exact (integer cents), no tolerance."""
    mismatches = []
    for account, expected in expected_balances.items():
        account = _require_account(account)
        expected_cents = _to_cents(expected, what="expected balance")
        actual = ledger.balance(account)
        if actual != expected_cents:
            mismatches.append(
                {"account": account, "expected": expected_cents, "actual": actual}
            )
    return {"ok": not mismatches, "mismatches": mismatches}
