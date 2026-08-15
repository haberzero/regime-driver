class ShopError(Exception):
    """Base class for all recoverable domain errors in the shop subsystem."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UnknownSKUError(ShopError):
    def __init__(self, sku: str):
        self.sku = sku
        super().__init__(f"unknown sku: {sku!r}")


class InsufficientStockError(ShopError):
    def __init__(self, sku: str, requested: int, available: int):
        self.sku = sku
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient stock for sku {sku!r}: "
            f"requested={requested}, available={available}"
        )


class InvalidQuantityError(ShopError):
    def __init__(self, sku: str, qty: object):
        self.sku = sku
        self.qty = qty
        super().__init__(f"invalid quantity for sku {sku!r}: {qty!r}")


class InvalidPriceError(ShopError):
    def __init__(self, sku: str, price: object):
        self.sku = sku
        self.price = price
        super().__init__(f"invalid price for sku {sku!r}: {price!r}")


class InvalidCouponError(ShopError):
    def __init__(self, coupon_code: str):
        self.coupon_code = coupon_code
        super().__init__(f"invalid coupon: {coupon_code!r}")
