from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Optional

from errors import (
    InvalidCouponError,
    InvalidPriceError,
    InvalidQuantityError,
    UnknownSKUError,
)


def _coerce_price(sku: str, price: object) -> Decimal:
    if isinstance(price, bool):
        raise InvalidPriceError(sku, price)
    if isinstance(price, Decimal):
        value = price
    elif isinstance(price, (int, float)):
        value = Decimal(str(price))
    elif isinstance(price, str):
        try:
            value = Decimal(price)
        except Exception:
            raise InvalidPriceError(sku, price)
    else:
        raise InvalidPriceError(sku, price)
    if not value.is_finite():
        raise InvalidPriceError(sku, price)
    return value


def _validate_quantity(sku: str, qty: object) -> None:
    if type(qty) is not int or qty <= 0:
        raise InvalidQuantityError(sku, qty)


DiscountStrategy = Callable[[Decimal, int, Optional[str]], Decimal]


class PriceCatalog:
    """Price table with a caller-registered, replaceable discount strategy."""

    def __init__(self, discount_strategy: Optional[DiscountStrategy] = None):
        self._prices = {}
        self._discount_strategy = discount_strategy

    def set_price(self, sku: str, price: object) -> None:
        value = _coerce_price(sku, price)
        if value <= 0:
            raise InvalidPriceError(sku, price)
        self._prices[sku] = value

    def price_of(self, sku: str) -> Decimal:
        if sku not in self._prices:
            raise UnknownSKUError(sku)
        return self._prices[sku]

    def set_discount_strategy(self, discount_strategy: Optional[DiscountStrategy]) -> None:
        self._discount_strategy = discount_strategy

    def discounted_price(
        self, sku: str, qty: object, coupon_code: Optional[str] = None
    ) -> Decimal:
        _validate_quantity(sku, qty)
        base = self.price_of(sku)
        if self._discount_strategy is None:
            if coupon_code not in (None, ""):
                raise InvalidCouponError(coupon_code)
            return base * qty
        total = self._discount_strategy(base, qty, coupon_code)
        if not isinstance(total, Decimal):
            total = Decimal(str(total))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
