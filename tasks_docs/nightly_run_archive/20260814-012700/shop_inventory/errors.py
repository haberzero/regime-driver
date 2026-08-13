"""Unified domain exceptions for the inventory/pricing/orders subsystem.

Every exception carries a human-readable ``message`` plus structured fields
so callers can react programmatically without parsing text.
"""


class DomainError(Exception):
    """Base class for all subsystem errors."""


class UnknownSKUError(DomainError):
    def __init__(self, sku):
        self.sku = sku
        self.code = "UNKNOWN_SKU"
        super().__init__(f"unknown SKU: {sku!r}")


class InsufficientStockError(DomainError):
    def __init__(self, sku, requested, available):
        self.sku = sku
        self.requested = requested
        self.available = available
        self.code = "INSUFFICIENT_STOCK"
        super().__init__(
            f"insufficient stock for SKU {sku!r}: "
            f"requested {requested}, available {available}"
        )


class InvalidQuantityError(DomainError):
    def __init__(self, sku, quantity):
        self.sku = sku
        self.quantity = quantity
        self.code = "INVALID_QUANTITY"
        super().__init__(
            f"invalid quantity for SKU {sku!r}: {quantity!r} "
            f"(must be a positive integer)"
        )


class InvalidPriceError(DomainError):
    def __init__(self, sku, price):
        self.sku = sku
        self.price = price
        self.code = "INVALID_PRICE"
        super().__init__(
            f"invalid price for SKU {sku!r}: {price!r} "
            f"(must be a positive number)"
        )


class InvalidCouponError(DomainError):
    def __init__(self, coupon_code):
        self.coupon_code = coupon_code
        self.code = "INVALID_COUPON"
        super().__init__(f"invalid coupon code: {coupon_code!r}")
