# double-entry payment ledger
#
# DESIGN DECISIONS (final):
#   A. Amount representation = int cents.
#      floats are the root cause of the 0.1+0.2 bug and are REJECTED at the API
#      boundary (TypeError); Decimal, str and bool are rejected too. Rationale:
#      int cents is the single canonical external amount type — auto-converting
#      float to cents silently reintroduces rounding (e.g. int(0.29*100) == 28),
#      and accepting Decimal would open a second parallel conversion boundary
#      for no benefit (Decimal(float) inherits the float's binary value anyway).
#      Rejected: float (binary rounding), Decimal (overhead + precision-context
#      pitfalls + inherits float's binary value when built from a float).
#
#   B. Idempotency = one key per LOGICAL OPERATION ("single authoritative
#      semantics"), kept in a per-ledger _op_keys set:
#          post     key = ("post",     account, ref)
#          transfer key = ("transfer", src, dst, ref)
#      Consequences:
#        - transfer is deduped by EXACTLY (ref, src, dst): a retry with the same
#          triple returns False; a different src (or dst) with the same ref is a
#          DIFFERENT transfer and is applied.
#        - post and transfer ref namespaces are ISOLATED by operation type: a
#          ref used by post('dst', ..) never blocks transfer(src, dst, ..), and
#          vice versa. Sharing a ref across operation types is a caller error
#          but can never silently drop or corrupt entries.
#
#   C. transfer rejects src == dst in pre-validation (ValueError): a self
#      transfer is never valid, and without this guard it would produce a
#      degenerate one-leg/zero-net entry set with misleading return semantics.
#
#   D. Every read (balance/count/snapshot/last_refs) takes the lock for a
#      linearizable snapshot. reconcile() derives ALL account balances from ONE
#      ledger.snapshot(), so a cross-account report can never mix entries taken
#      at different moments.
#
# External contract: module-level reconcile(ledger, expected_balances) kept.
# Its return changed from a list of bad accounts to a structured report
#   {"ok": bool, "mismatches": [{"account", "expected", "actual"}]}
# with exact integer comparison (no tolerance).
import time
import threading
from collections import namedtuple


class StorageFullError(Exception):
    """Raised when a post/transfer would exceed the configured capacity."""


LedgerEntry = namedtuple("LedgerEntry", ["seq", "account", "amount", "ref", "ts"])


class Ledger:
    def __init__(self, max_entries=None):
        if max_entries is not None and (
            isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 0
        ):
            raise ValueError(
                "max_entries must be a non-negative int or None, got %r" % (max_entries,)
            )
        self._entries = []
        self._op_keys = set()
        self._seq = 0
        self._max_entries = max_entries
        self._lock = threading.Lock()

    @staticmethod
    def _check_amount(amount):
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError(
                "amount must be an integer number of cents, got %r" % (amount,)
            )

    def _append(self, account, amount, ref):
        """Record one leg. Caller must hold the lock; amount and capacity are
        validated by the public operations before this is reached."""
        self._seq += 1
        self._entries.append(
            LedgerEntry(
                seq=self._seq, account=account, amount=amount, ref=ref,
                ts=time.time(),
            )
        )

    def post(self, account, amount, ref):
        """Idempotent single entry. True if newly recorded, False if the same
        post operation (account, ref) was already applied."""
        self._check_amount(amount)
        key = ("post", account, ref)
        with self._lock:
            if key in self._op_keys:
                return False
            if self._max_entries is not None and len(self._entries) >= self._max_entries:
                raise StorageFullError(
                    "ledger full: max_entries=%s" % (self._max_entries,)
                )
            self._op_keys.add(key)
            self._append(account, amount, ref)
            return True

    def balance(self, account):
        """Exact int-cents balance read under the lock (consistent snapshot)."""
        with self._lock:
            return sum(
                e.amount for e in self._entries if e.account == account
            )

    def transfer(self, src, dst, amount, ref):
        """Atomic, idempotent two-leg transfer.

        Atomic: the whole operation runs under one lock with idempotency and
        capacity validated before any leg is appended — all-or-nothing.
        Idempotent by the (ref, src, dst) triple: a retry of the same transfer
        returns False and changes nothing; the same ref with a different src or
        dst is a separate transfer. post and transfer ref namespaces do not
        interfere. Returns True if newly applied, False otherwise.
        """
        self._check_amount(amount)
        if src == dst:
            raise ValueError("transfer requires src != dst")
        key = ("transfer", src, dst, ref)
        with self._lock:
            if key in self._op_keys:
                return False
            if self._max_entries is not None and len(self._entries) + 2 > self._max_entries:
                raise StorageFullError(
                    "ledger full: max_entries=%s" % (self._max_entries,)
                )
            self._op_keys.add(key)
            self._append(src, -amount, ref)
            self._append(dst, amount, ref)
            return True

    def idempotent_transfer(self, src, dst, amount, ref):
        """Explicit idempotent-transfer entry point; delegates to transfer,
        which already guarantees only-once semantics."""
        return self.transfer(src, dst, amount, ref)

    def count(self):
        with self._lock:
            return len(self._entries)

    def snapshot(self):
        """Detached copy of all entries, atomically consistent."""
        with self._lock:
            return list(self._entries)

    def last_refs(self, n=10):
        with self._lock:
            return [e.ref for e in self._entries[-n:]]


def reconcile(ledger, expected_balances):
    """Structured reconciliation report computed from a single ledger snapshot,
    so all account balances come from one point in time (no cross-snapshot mix).
    Exact integer comparison, no tolerance."""
    balances = {}
    for e in ledger.snapshot():
        balances[e.account] = balances.get(e.account, 0) + e.amount
    mismatches = []
    for acct, want in expected_balances.items():
        actual = balances.get(acct, 0)
        if actual != want:
            mismatches.append({"account": acct, "expected": want, "actual": actual})
    return {"ok": len(mismatches) == 0, "mismatches": mismatches}
