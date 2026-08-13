"""Inventory domain: SKU registry + thread-safe stock ledger.

Pricing lives in ``pricing.py``; this module only owns SKU identity (name)
and stock quantities. ``restock``/``take`` are atomic per SKU, guarded by a
lock, so concurrent mutators never lose updates.
"""
from threading import Lock

from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSKUError,
)


def _is_valid_qty(n):
    return isinstance(n, int) and not isinstance(n, bool) and n > 0


class Inventory:
    def __init__(self):
        self._names = {}
        self._qty = {}
        self._lock = Lock()

    def add_item(self, sku, name):
        """Register a SKU (stock starts at 0) or update its name.

        Unlike the legacy version, an existing SKU's name IS updated
        (defect 1 root fix), not silently dropped.
        """
        if not isinstance(sku, str) or not sku:
            raise UnknownSKUError(sku)
        if not isinstance(name, str) or not name:
            raise ValueError(f"name for {sku!r} must be a non-empty string")
        with self._lock:
            self._names[sku] = name
            self._qty.setdefault(sku, 0)

    def has_sku(self, sku):
        with self._lock:
            return sku in self._names

    def name_of(self, sku):
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            return self._names[sku]

    def stock_level(self, sku):
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            return self._qty[sku]

    def restock(self, sku, n):
        """Add ``n`` units of ``sku``. Rejects non-positive quantities
        (defect 3 root fix) and unknown SKUs."""
        if not _is_valid_qty(n):
            raise InvalidQuantityError(sku, n)
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            self._qty[sku] += n

    def take(self, sku, n):
        """Atomically remove ``n`` units or raise without mutating."""
        if not _is_valid_qty(n):
            raise InvalidQuantityError(sku, n)
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            available = self._qty[sku]
            if available < n:
                raise InsufficientStockError(sku, n, available)
            self._qty[sku] = available - n
