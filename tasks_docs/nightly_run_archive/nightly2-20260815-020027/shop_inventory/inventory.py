import threading

from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSKUError,
)


def _validate_quantity(sku: str, n: object) -> None:
    if type(n) is not int or n <= 0:
        raise InvalidQuantityError(sku, n)


class Inventory:
    """Stock warehouse: SKU registration plus atomic restock/take operations."""

    def __init__(self):
        self._names = {}
        self._qty = {}
        self._lock = threading.Lock()

    def add_item(self, sku: str, name: str) -> None:
        if not isinstance(sku, str) or not sku:
            raise TypeError("sku must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise TypeError("name must be a non-empty string")
        with self._lock:
            self._names[sku] = name
            self._qty.setdefault(sku, 0)

    def name_of(self, sku: str) -> str:
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            return self._names[sku]

    def restock(self, sku: str, n: object) -> None:
        _validate_quantity(sku, n)
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            self._qty[sku] += n

    def take(self, sku: str, n: object) -> None:
        _validate_quantity(sku, n)
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            if self._qty[sku] < n:
                raise InsufficientStockError(sku, n, self._qty[sku])
            self._qty[sku] -= n

    def stock_level(self, sku: str) -> int:
        with self._lock:
            if sku not in self._names:
                raise UnknownSKUError(sku)
            return self._qty[sku]
