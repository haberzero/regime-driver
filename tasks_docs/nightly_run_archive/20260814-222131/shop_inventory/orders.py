from dataclasses import dataclass
from decimal import Decimal

from errors import InvalidQuantityError


@dataclass(frozen=True)
class OrderLine:
    sku: str
    qty: int
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Order:
    customer: str
    lines: tuple

    def total(self) -> Decimal:
        return sum((line.amount for line in self.lines), start=Decimal("0"))


def place_order(catalog, inventory, lines, customer=None, coupon_code=None):
    parsed = []
    for sku, qty in lines:
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise InvalidQuantityError(sku, qty)
        catalog.price_of(sku)
        inventory.stock_level(sku)
        parsed.append((sku, qty))

    with inventory.lock:
        amounts = []
        for sku, qty in parsed:
            amounts.append((sku, qty, catalog.discounted_price(sku, qty, coupon_code)))
        taken = []
        try:
            for sku, qty in parsed:
                inventory.take(sku, qty)
                taken.append((sku, qty))
        except Exception:
            for sku, qty in reversed(taken):
                inventory.restock(sku, qty)
            raise

    lines_out = tuple(
        OrderLine(sku=sku, qty=qty, unit_price=catalog.price_of(sku), amount=amount)
        for sku, qty, amount in amounts
    )
    return Order(customer=customer, lines=lines_out)
