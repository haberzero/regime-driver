class ShopError(Exception):
    def __init__(self, message, **fields):
        super().__init__(message)
        self.message = message
        self.fields = dict(fields)
        for key, value in self.fields.items():
            setattr(self, key, value)

    def __str__(self):
        return self.message

    def to_dict(self):
        return {"message": self.message, "fields": dict(self.fields)}


class UnknownSKUError(ShopError):
    def __init__(self, sku):
        super().__init__(f"unknown SKU: {sku!r}", sku=sku)


class InsufficientStockError(ShopError):
    def __init__(self, sku, requested, available):
        super().__init__(
            f"insufficient stock for SKU {sku!r}: requested {requested}, available {available}",
            sku=sku,
            requested=requested,
            available=available,
        )


class InvalidQuantityError(ShopError):
    def __init__(self, sku, quantity):
        super().__init__(
            f"invalid quantity {quantity!r} for SKU {sku!r} (must be a positive integer)",
            sku=sku,
            quantity=quantity,
        )


class InvalidCouponError(ShopError):
    def __init__(self, coupon_code):
        super().__init__(f"invalid coupon code: {coupon_code!r}", coupon_code=coupon_code)


class InvalidPriceError(ShopError):
    def __init__(self, sku, price):
        super().__init__(
            f"invalid price {price!r} for SKU {sku!r} (must be a positive number)",
            sku=sku,
            price=price,
        )
