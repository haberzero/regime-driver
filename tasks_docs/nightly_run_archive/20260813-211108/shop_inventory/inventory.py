"""Inventory domain: SKU management and atomic stock operations.

The :class:`Inventory` owns SKU names and quantities only; pricing lives in the
pricing domain (:mod:`pricing`).  All quantity mutations are serialized through
a single lock so concurrent ``restock`` / ``take`` never lose updates.
"""

import threading

from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSKUError,
)


def _is_valid_quantity(n, *, allow_zero):
    """True when *n* is an int (not bool) >= 0 or >= 1 per *allow_zero*."""
    if isinstance(n, bool) or not isinstance(n, int):
        return False
    return n >= 0 if allow_zero else n > 0


class Inventory:
    """A warehouse of SKUs: names + current stock levels."""

    def __init__(self):
        self._names = {}
        self._qty = {}
        self._lock = threading.Lock()

    def add_item(self, sku, name):
        """Register a SKU or update its display name (name is always kept)."""
        with self._lock:
            self._names[sku] = name
            self._qty.setdefault(sku, 0)

    def name_of(self, sku):
        """Return the display name of *sku* (raises if unknown)."""
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            return self._names[sku]

    def stock_level(self, sku):
        """Return the current stock level of *sku* (raises if unknown)."""
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            return self._qty[sku]

    def restock(self, sku, n):
        """Add *n* units to *sku* atomically.

        Raises ``UnknownSKUError`` for unknown SKUs and
        ``InvalidQuantityError`` for negative or non-integer *n*.
        """
        if not _is_valid_quantity(n, allow_zero=True):
            raise InvalidQuantityError(
                sku, n, f"invalid restock quantity {n!r} for {sku!r}: must be a non-negative integer"
            )
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            self._qty[sku] += n

    def take(self, sku, n):
        """Remove *n* units from *sku* atomically.

        Raises ``InvalidQuantityError`` for invalid *n*,
        ``UnknownSKUError`` for unknown SKUs and
        ``InsufficientStockError`` when stock is short (stock is untouched).
        """
        if not _is_valid_quantity(n, allow_zero=False):
            raise InvalidQuantityError(
                sku, n, f"invalid take quantity {n!r} for {sku!r}: must be a positive integer"
            )
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            if self._qty[sku] < n:
                raise InsufficientStockError(sku, requested=n, available=self._qty[sku])
            self._qty[sku] -= n
