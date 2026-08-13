"""Order domain: OrderLine / Order / place_order.

``place_order`` follows the required sequence: validate stock -> deduct stock
-> price via catalog. Any failure after deduction rolls the stock back, so
an order either fully succeeds or leaves inventory untouched (atomicity).
Prices are captured into the order at placement time; ``Order.total`` is a
pure function of the lines and never touches inventory again (defect 5 fix:
no second deduction, no re-computation against the ledger).
"""
from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSKUError,
)


class OrderLine:
    __slots__ = ("sku", "qty", "unit_price")

    def __init__(self, sku, qty, unit_price):
        self.sku = sku
        self.qty = qty
        self.unit_price = unit_price

    @property
    def total(self):
        return self.unit_price * self.qty

    def __eq__(self, other):
        if not isinstance(other, OrderLine):
            return NotImplemented
        return (self.sku, self.qty, self.unit_price) == (
            other.sku,
            other.qty,
            other.unit_price,
        )

    def __repr__(self):
        return f"OrderLine(sku={self.sku!r}, qty={self.qty}, unit_price={self.unit_price})"


class Order:
    def __init__(self, customer, lines):
        self.customer = customer
        self.lines = list(lines)

    def total(self):
        return sum(line.total for line in self.lines)


def _is_valid_qty(n):
    return isinstance(n, int) and not isinstance(n, bool) and n > 0


def place_order(catalog, inventory, lines, customer, coupon_code=None):
    """Validate stock, deduct it atomically, price via ``catalog``.

    ``lines`` is an iterable of ``(sku, qty)`` pairs. Raises the relevant
    domain error and guarantees stock is unchanged on failure.
    """
    validated = []
    for sku, qty in lines:
        if not isinstance(sku, str) or not sku:
            raise UnknownSKUError(sku)
        if not _is_valid_qty(qty):
            raise InvalidQuantityError(sku, qty)
        if not inventory.has_sku(sku):
            raise UnknownSKUError(sku)
        if not catalog.has_sku(sku):
            raise UnknownSKUError(sku)
        available = inventory.stock_level(sku)
        if available < qty:
            raise InsufficientStockError(sku, qty, available)
        validated.append((sku, qty))

    deducted = []
    order_lines = []
    try:
        for sku, qty in validated:
            inventory.take(sku, qty)
            deducted.append((sku, qty))
        for sku, qty in validated:
            total = catalog.discounted_price(sku, qty, coupon_code)
            order_lines.append(OrderLine(sku, qty, total / qty))
    except Exception:
        for sku, qty in reversed(deducted):
            inventory.restock(sku, qty)
        raise

    return Order(customer, order_lines)
