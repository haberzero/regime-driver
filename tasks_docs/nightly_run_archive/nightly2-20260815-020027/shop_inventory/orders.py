from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Tuple

from errors import InvalidQuantityError
from inventory import Inventory
from pricing import PriceCatalog


@dataclass(frozen=True)
class OrderLine:
    sku: str
    qty: int
    unit_price: Decimal


class Order:
    def __init__(self, customer: Optional[str], lines: Iterable[OrderLine]):
        self.customer = customer
        self.lines = tuple(lines)

    @property
    def total(self) -> Decimal:
        return sum(
            (line.unit_price * line.qty for line in self.lines), Decimal("0")
        )


def place_order(
    catalog: PriceCatalog,
    inventory: Inventory,
    lines: Iterable[Tuple[str, object]],
    customer: Optional[str] = None,
) -> Order:
    prepared = []
    for sku, qty in lines:
        if not isinstance(sku, str) or not sku:
            raise TypeError("sku must be a non-empty string")
        if type(qty) is not int or qty <= 0:
            raise InvalidQuantityError(sku, qty)
        unit_price = catalog.price_of(sku)
        prepared.append((sku, qty, unit_price))

    taken = []
    try:
        for sku, qty, _unit_price in prepared:
            inventory.take(sku, qty)
            taken.append((sku, qty))
    except Exception:
        for sku, qty in reversed(taken):
            inventory.restock(sku, qty)
        raise

    order_lines = tuple(
        OrderLine(sku, qty, unit_price) for sku, qty, unit_price in prepared
    )
    return Order(customer, order_lines)
