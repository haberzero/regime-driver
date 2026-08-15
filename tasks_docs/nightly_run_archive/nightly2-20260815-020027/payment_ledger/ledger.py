# legacy double-entry payment ledger (deliberately buggy)
import time
import threading


class Ledger:
    def __init__(self):
        self._entries = []
        self._seq = 0
        self._lock = threading.Lock()

    def post(self, account, amount, ref):
        self._seq += 1
        self._entries.append({
            "seq": self._seq, "account": account, "amount": amount,
            "ref": ref, "ts": time.time(),
        })

    def balance(self, account):
        b = 0.0
        for e in self._entries:
            if e["account"] == account:
                b += e["amount"]
        return b

    def transfer(self, src, dst, amount, ref):
        with self._lock:
            self.post(src, -amount, ref)
            self.post(dst, amount, ref)

    def count(self):
        return len(self._entries)

    def last_refs(self, n=10):
        return [e["ref"] for e in self._entries[-n:]]


def reconcile(ledger, expected_balances):
    bad = []
    for acct, want in expected_balances.items():
        if abs(ledger.balance(acct) - want) > 1e-9:
            bad.append(acct)
    return bad
