"""Pricing domain: price catalog and a strategy-injected discount system.

Discounts are configured by registering a *strategy function* per coupon code
(``register_coupon``).  A strategy is a pure ``callable(base_subtotal) ->
discounted_subtotal``; callers decide whether the policy is threshold-based
(满减) or percentage-based (打折).
"""

from errors import (
    InvalidCouponError,
    InvalidPriceError,
    InvalidQuantityError,
    UnknownSKUError,
)


def _is_valid_price(price):
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return False
    return price > 0


class PriceCatalog:
    """Unit prices per SKU plus registered coupon strategies."""

    def __init__(self):
        self._prices = {}
        self._coupons = {}

    def set_price(self, sku, price):
        """Set (or create) the unit price for *sku*; validates price > 0."""
        if not _is_valid_price(price):
            raise InvalidPriceError(sku, price)
        self._prices[sku] = float(price)

    def price_of(self, sku):
        """Return the unit price of *sku*; raise if not priced."""
        try:
            return self._prices[sku]
        except KeyError:
            raise UnknownSKUError(sku) from None

    def register_coupon(self, code, strategy):
        """Register (or replace) the discount strategy for a coupon code."""
        if not isinstance(code, str) or not code:
            raise InvalidCouponError(code, f"coupon code must be a non-empty string, got {code!r}")
        if not callable(strategy):
            raise InvalidCouponError(code, f"strategy for {code!r} must be callable")
        self._coupons[code] = strategy

    def remove_coupon(self, code):
        """Remove a registered coupon; unknown codes are ignored."""
        self._coupons.pop(code, None)

    def discounted_price(self, sku, qty, coupon_code):
        """Return the discounted line total for *qty* units of *sku*.

        Validates quantity and SKU, then applies the registered strategy for
        *coupon_code* to the base subtotal and rounds to 2 decimals.
        """
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise InvalidQuantityError(
                sku, qty, f"invalid quantity {qty!r} for {sku!r}: must be a positive integer"
            )
        unit = self.price_of(sku)
        try:
            strategy = self._coupons[coupon_code]
        except KeyError:
            raise InvalidCouponError(coupon_code) from None
        base = unit * qty
        return round(float(strategy(base)), 2)
