import threading

from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    InvalidPriceError,
    UnknownSKUError,
)


def _require_positive_int(sku, n):
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise InvalidQuantityError(sku, n)


def _require_positive_price(sku, price):
    if isinstance(price, bool):
        raise InvalidPriceError(sku, price)
    if isinstance(price, str):
        try:
            value = float(price)
        except ValueError:
            raise InvalidPriceError(sku, price) from None
    elif isinstance(price, (int, float)):
        value = price
    else:
        raise InvalidPriceError(sku, price)
    if value <= 0:
        raise InvalidPriceError(sku, price)


class Inventory:
    def __init__(self):
        self._skus = {}
        self._qty = {}
        self.lock = threading.RLock()

    def add_item(self, sku, name, price):
        if not isinstance(sku, str) or not sku:
            raise UnknownSKUError(sku)
        _require_positive_price(sku, price)
        with self.lock:
            self._skus[sku] = name
            self._qty.setdefault(sku, 0)

    def rename(self, sku, name):
        self._ensure_known(sku)
        with self.lock:
            self._skus[sku] = name

    def restock(self, sku, n):
        self._ensure_known(sku)
        _require_positive_int(sku, n)
        with self.lock:
            self._qty[sku] += n

    def take(self, sku, n):
        self._ensure_known(sku)
        _require_positive_int(sku, n)
        with self.lock:
            if self._qty[sku] < n:
                raise InsufficientStockError(sku, n, self._qty[sku])
            self._qty[sku] -= n

    def stock_level(self, sku):
        self._ensure_known(sku)
        with self.lock:
            return self._qty[sku]

    def name_of(self, sku):
        self._ensure_known(sku)
        with self.lock:
            return self._skus[sku]

    def _ensure_known(self, sku):
        if not isinstance(sku, str) or sku not in self._skus:
            raise UnknownSKUError(sku)
