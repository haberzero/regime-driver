"""Unified domain exceptions for the inventory / pricing / orders subsystem.

Every domain error derives from :class:`InventoryError` so callers can catch a
single base type, while each concrete exception carries structured fields for
programmatic handling.
"""


class InventoryError(Exception):
    """Base class for all subsystem errors."""


class UnknownSKUError(InventoryError):
    """A SKU is not known to the relevant domain (catalog or inventory)."""

    def __init__(self, sku, message=None):
        self.sku = sku
        self.message = message or f"unknown SKU: {sku!r}"
        super().__init__(self.message)


class InsufficientStockError(InventoryError):
    """A take operation would exceed the available stock."""

    def __init__(self, sku, requested, available, message=None):
        self.sku = sku
        self.requested = requested
        self.available = available
        self.message = message or (
            f"insufficient stock for {sku!r}: "
            f"requested {requested}, available {available}"
        )
        super().__init__(self.message)


class InvalidQuantityError(InventoryError):
    """A quantity argument is not a valid positive (or non-negative) integer."""

    def __init__(self, sku, quantity, message=None):
        self.sku = sku
        self.quantity = quantity
        self.message = message or (
            f"invalid quantity {quantity!r} for {sku!r}: must be an integer"
        )
        super().__init__(self.message)


class InvalidCouponError(InventoryError):
    """A coupon code is not registered / not usable."""

    def __init__(self, coupon_code, message=None):
        self.coupon_code = coupon_code
        self.message = message or f"invalid coupon code: {coupon_code!r}"
        super().__init__(self.message)


class InvalidPriceError(InventoryError):
    """A price is not a positive number (<= 0 or non-numeric)."""

    def __init__(self, sku, price, message=None):
        self.sku = sku
        self.price = price
        self.message = message or (
            f"invalid price {price!r} for {sku!r}: must be a positive number"
        )
        super().__init__(self.message)
