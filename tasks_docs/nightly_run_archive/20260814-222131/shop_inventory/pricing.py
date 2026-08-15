from decimal import Decimal, InvalidOperation

from errors import InvalidQuantityError, InvalidPriceError, UnknownSKUError


class PriceCatalog:
    def __init__(self):
        self._prices = {}
        self._strategy = None

    def set_price(self, sku, price):
        if not isinstance(sku, str) or not sku:
            raise UnknownSKUError(sku)
        if isinstance(price, bool):
            raise InvalidPriceError(sku, price)
        if isinstance(price, str):
            try:
                value = Decimal(price)
            except (InvalidOperation, ValueError):
                raise InvalidPriceError(sku, price) from None
        elif isinstance(price, (int, float, Decimal)):
            value = Decimal(str(price))
        else:
            raise InvalidPriceError(sku, price)
        if value <= 0:
            raise InvalidPriceError(sku, price)
        self._prices[sku] = value

    def price_of(self, sku):
        if sku not in self._prices:
            raise UnknownSKUError(sku)
        return self._prices[sku]

    def set_discount_strategy(self, strategy):
        self._strategy = strategy

    def discounted_price(self, sku, qty, coupon_code=None):
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise InvalidQuantityError(sku, qty)
        base = self.price_of(sku) * qty
        if self._strategy is None:
            return base
        return self._strategy(self, sku, qty, coupon_code)


def make_full_reduction(threshold, reduction):
    def strategy(catalog, sku, qty, coupon_code):
        if coupon_code is not None and coupon_code != "FULL":
            from errors import InvalidCouponError

            raise InvalidCouponError(coupon_code)
        total = catalog.price_of(sku) * qty
        if total >= threshold:
            return total - reduction
        return total

    return strategy


def make_percent_off(percent, required_coupon=None):
    try:
        pct = Decimal(str(percent))
    except (InvalidOperation, ValueError):
        raise ValueError("percent must be a number between 0 and 100") from None
    if not 0 <= pct <= 100:
        raise ValueError("percent must be between 0 and 100")
    factor = Decimal("100") - pct

    def strategy(catalog, sku, qty, coupon):
        if required_coupon is not None and coupon != required_coupon:
            from errors import InvalidCouponError

            raise InvalidCouponError(coupon)
        total = catalog.price_of(sku) * qty
        return total * factor / Decimal("100")

    return strategy
