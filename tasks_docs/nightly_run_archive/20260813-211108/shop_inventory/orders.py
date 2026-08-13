"""Order domain: order lines, orders, and atomic order placement.

``place_order`` orchestrates pricing (:mod:`pricing`) and inventory
(:mod:`inventory`): it resolves every unit price first, validates all stock
without mutating it, then deducts stock as one atomic unit — rolling back
already-taken lines on any failure.
"""

from errors import (
    InsufficientStockError,
    InvalidPriceError,
    InvalidQuantityError,
)


def _is_valid_qty(qty):
    return not isinstance(qty, bool) and isinstance(qty, int) and qty > 0


def _is_valid_price(price):
    return not isinstance(price, bool) and isinstance(price, (int, float)) and price > 0


class OrderLine:
    """One ordered line: SKU, quantity and the unit price at order time."""

    def __init__(self, sku, qty, unit_price):
        if not _is_valid_qty(qty):
            raise InvalidQuantityError(
                sku, qty, f"invalid quantity {qty!r} for {sku!r}: must be a positive integer"
            )
        if not _is_valid_price(unit_price):
            raise InvalidPriceError(sku, unit_price)
        self.sku = sku
        self.qty = qty
        self.unit_price = unit_price

    @property
    def total(self):
        """Line subtotal rounded to 2 decimals."""
        return round(self.unit_price * self.qty, 2)


class Order:
    """A customer order made of :class:`OrderLine` objects."""

    def __init__(self, customer, lines):
        self.customer = customer
        self.lines = list(lines)

    @property
    def total(self):
        """Order total computed purely from line data (never touches stock)."""
        return round(sum(line.total for line in self.lines), 2)


def place_order(catalog, inventory, lines, customer=None):
    """Atomically place an order.

    For each ``(sku, qty)`` line: price is resolved from *catalog* (unknown
    SKU raises ``UnknownSKUError``) and the line is validated; then every
    line's stock availability is checked without mutating inventory; finally
    stock is deducted for all lines.  Any failure leaves inventory unchanged
    (already-taken lines are rolled back before re-raising).

    Returns the created :class:`Order`.
    """
    order_lines = []
    for sku, qty in lines:
        unit_price = catalog.price_of(sku)
        order_lines.append(OrderLine(sku, qty, unit_price))

    for line in order_lines:
        available = inventory.stock_level(line.sku)
        if available < line.qty:
            raise InsufficientStockError(line.sku, requested=line.qty, available=available)

    taken = []
    try:
        for line in order_lines:
            inventory.take(line.sku, line.qty)
            taken.append(line)
    except Exception:
        for line in reversed(taken):
            inventory.restock(line.sku, line.qty)
        raise

    return Order(customer, order_lines)
