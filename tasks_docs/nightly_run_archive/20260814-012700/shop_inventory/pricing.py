"""Pricing domain: PriceCatalog + configurable discount strategies.

Discounts use *strategy-function injection* (see DESIGN.md): the caller
registers a coupon code bound to a strategy function
``f(unit_price, qty) -> discounted line total``. Two ready-made strategy
factories are provided: ``percent_discount`` (折·percentage off) and
``amount_off`` (满减·fixed amount off above a threshold).
"""
from errors import (
    InvalidCouponError,
    InvalidPriceError,
    InvalidQuantityError,
    UnknownSKUError,
)


def _is_valid_price(p):
    return isinstance(p, (int, float)) and not isinstance(p, bool) and p > 0


def _is_valid_qty(n):
    return isinstance(n, int) and not isinstance(n, bool) and n > 0


def percent_discount(percent):
    """Strategy factory: pay ``(100 - percent)%`` of the base line total."""
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        raise ValueError("percent must be a number")
    if percent <= 0 or percent > 100:
        raise ValueError("percent must be in (0, 100]")

    def strategy(unit_price, qty):
        return unit_price * qty * (1.0 - percent / 100.0)

    return strategy


def amount_off(threshold, discount):
    """Strategy factory: subtract ``discount`` once base total >= ``threshold``."""
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold <= 0:
        raise ValueError("threshold must be a positive number")
    if isinstance(discount, bool) or not isinstance(discount, (int, float)) or discount < 0:
        raise ValueError("discount must be a non-negative number")

    def strategy(unit_price, qty):
        total = unit_price * qty
        if total >= threshold:
            return total - discount
        return total

    return strategy


class PriceCatalog:
    def __init__(self):
        self._prices = {}
        self._discounts = {}

    def set_price(self, sku, price):
        """Set/overwrite a SKU's unit price. Rejects non-numeric, bool,
        zero and negative prices (defect 4 root fix)."""
        if not _is_valid_price(price):
            raise InvalidPriceError(sku, price)
        self._prices[sku] = price

    def price_of(self, sku):
        if sku not in self._prices:
            raise UnknownSKUError(sku)
        return self._prices[sku]

    def has_sku(self, sku):
        return sku in self._prices

    def register_discount(self, coupon_code, strategy):
        """Bind a coupon code to a discount strategy injected by the caller."""
        if not callable(strategy):
            raise TypeError("strategy must be callable")
        self._discounts[coupon_code] = strategy

    def discounted_price(self, sku, qty, coupon_code=None):
        """Total price for ``qty`` units of ``sku``, applying ``coupon_code``."""
        if not _is_valid_qty(qty):
            raise InvalidQuantityError(sku, qty)
        unit = self.price_of(sku)  # raises UnknownSKUError
        if coupon_code is None:
            return unit * qty
        strategy = self._discounts.get(coupon_code)
        if strategy is None:
            raise InvalidCouponError(coupon_code)
        total = strategy(unit, qty)
        if isinstance(total, bool) or not isinstance(total, (int, float)) or total < 0:
            raise InvalidCouponError(coupon_code)
        return total
